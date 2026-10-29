"""Aggregate saved MCP job results without additional model calls."""
import argparse
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_relations import verify_bundle
from mapmaker.relation_experiment import collect, evaluate, relation_set


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    args = p.parse_args()
    root = args.root
    freeze = read(root/'freeze.json')
    groups = {}
    execution_ms = 0
    for file in sorted((root/'results').glob('*.json')):
        job = read(file)
        result = job['result']
        execution_ms += result.get('executionTime', 0)
        if result['status'] != 'COMPLETED':
            continue
        output = result['output']
        output = output[0] if isinstance(output,list) and len(output)==1 else output
        if not isinstance(output,dict) or not output.get('choices'):
            continue
        choice = output['choices'][0]
        if choice['finish_reason'] != 'stop':
            continue
        groups.setdefault((job['scene'],job['order']),{})[job['request_id']] = choice['message']['content']
    reports, predictions = [], {}
    detail = []
    for (scene,order), responses in sorted(groups.items()):
        bundle = verify_bundle(root/scene/order)
        if len(responses) != len(bundle['requests']):
            continue
        if sha(root/scene/'labels.json') != freeze['labels'][scene]:
            raise ValueError('Frozen reference labels changed')
        result = collect(bundle, responses)
        result['inputs_sha256'] = sha(root/scene/order/'inputs.json')
        predictions[(scene,order)] = result
        dest = root/scene/('qwen3-'+order+'-mcp')
        write(dest/'responses.json',responses)
        write(dest/'relations.json',result)
        row = dict(scene=scene,order=order,valid=result['valid'],
                   invalid_requests=[r for r in result['records'] if r['status']!='valid'],
                   graph_issues=result['graph_issues'])
        if result['valid']:
            row['evaluation']=evaluate(result,read(root/scene/'labels.json'))
        write(dest/'evaluation.json',row)
        reports.append(row)
        display={o['object_id']:o['id']+' '+o['name'] for o in bundle['objects']}
        detail.append('<h2>'+html.escape(scene+' / '+order)+'</h2>')
        detail.append('<img style="max-width:700px;width:100%" src="'+scene+'/'+order+'/overview.png">')
        detail.append('<pre>'+html.escape(str({k:v for k,v in row.items() if k!='invalid_requests'}))+'</pre>')
        for record in result['records']:
            detail.append('<details><summary>'+html.escape(record['request_id']+' '+record['status'])+'</summary><pre>'+html.escape(record['raw_response'])+'</pre></details>')
        detail.append('<table><tr><th>Subject</th><th>Relation</th><th>Target</th><th>Evidence</th></tr>')
        for r in result['relations']:
            values=[display[r['subject']],r['relation'],display.get(r['target'],r['target']),r['reason']]
            detail.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in values)+'</tr>')
        detail.append('</table>')
    consistency=[]
    for scene in freeze['labels']:
        a,b=predictions.get((scene,'forward')),predictions.get((scene,'reverse'))
        if a and b:
            if a['valid'] and b['valid']:
                changed={r[0] for r in relation_set(a)^relation_set(b)} | (set(a['unresolved'])^set(b['unresolved']))
                consistency.append(dict(scene=scene,objects=len(a['objects']),consistent=len(a['objects'])-len(changed),changed=sorted(changed)))
            else:
                consistency.append(dict(scene=scene,not_scored='invalid relation response'))
    report=dict(human_verified=False,scope='selected three-scene pilot only',reports=reports,
                consistency=consistency,job_execution_seconds=execution_ms/1000,
                timing_note='Excludes cold start and billed idle; not billed cost.')
    write(root/'report.json',report)
    page='<!doctype html><meta charset="utf-8"><title>Support relation pilot</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:16px}td,th{border:1px solid #bbb;padding:8px}table{border-collapse:collapse}pre{white-space:pre-wrap}summary{cursor:pointer}</style>'
    page+='<h1>Support relation pilot — preliminary, not human verified</h1><p>Original geometry is unchanged. Three selected scenes are not a held-out benchmark.</p>'
    (root/'report.html').write_text(page+''.join(detail),encoding='utf-8')
    print(__import__('json').dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
