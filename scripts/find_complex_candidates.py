import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scripts.find_presentation_candidates as base
base.OUT=base.ROOT/'docs/assets/ram-qwen-filter-complex'
base.SOURCES=[
 ('office-a','https://fufugaga.com/blogs/news/the-ideal-home-office-what-furniture-stores-wont-tell-you','https://fufugaga.com/cdn/shop/articles/img_1773724409838.png?v=1773724421&width=2048'),
 ('office-b','https://www.lundia.co.uk/blogs/open-shelving-unit/how-to-configure-and-expand-your-lundia-open-shelving-unit-a-step-by-step-guide','https://www.lundia.co.uk/cdn/shop/articles/Expand-Your-Lundia-Open-Shelving-Unit_700x.png?v=1765302418'),
 ('office-c','https://zior.in/collections/study-room','https://zior.in/cdn/shop/collections/ChatGPT_Image_Dec_20_2025_04_44_50_PM.png?v=1766229311'),
 ('office-d','https://blenderartists.org/t/minimal-study-room/1517261','https://blenderartists.org/uploads/default/original/4X/c/1/b/c1bbca68b3e7ca1ad014b8ccc5d35b6437897d1e.jpeg'),
]
if __name__=='__main__':
 import requests
 base.SOURCES=[r for r in base.SOURCES if requests.get(r[2],timeout=45).status_code==200]
 base.main()
