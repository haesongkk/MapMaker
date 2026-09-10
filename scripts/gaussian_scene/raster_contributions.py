"""Exact front-to-back pixel contribution weights from the installed gsplat API."""
import torch
from gsplat.cuda._wrapper import rasterize_to_indices_in_range

@torch.no_grad()
def contributions(meta):
    width, height = meta['width'], meta['height']
    assert meta['means2d'].ndim == 3 and meta['means2d'].shape[0] == 1, 'Use one camera and packed=False'
    gids, pixels, cameras = rasterize_to_indices_in_range(
        0, 1_000_000, torch.ones((1, height, width), device=meta['means2d'].device),
        meta['means2d'], meta['conics'], meta['opacities'], width, height,
        meta['tile_size'], meta['isect_offsets'], meta['flatten_ids'])
    if not len(gids):
        return gids, pixels, torch.empty(0, device=gids.device)
    # The CUDA kernel emits contiguous, depth-ordered lists for each pixel.
    delta = meta['means2d'][0, gids] - torch.stack((pixels % width + .5, pixels // width + .5), dim=-1)
    conic = meta['conics'][0, gids]
    sigma = .5 * (conic[:, 0] * delta[:, 0] ** 2 + conic[:, 2] * delta[:, 1] ** 2) + conic[:, 1] * delta[:, 0] * delta[:, 1]
    alpha = (meta['opacities'][0, gids] * torch.exp(-sigma)).clamp_max(.999)
    counts = torch.bincount(pixels, minlength=width * height)
    starts = torch.cat((torch.zeros(1, device=gids.device, dtype=torch.int64), counts.cumsum(0)[:-1]))
    # Float64 prevents global prefix subtraction from erasing small weights.
    prefix = torch.cat((torch.zeros(1, device=gids.device, dtype=torch.float64), torch.log1p(-alpha.double()).cumsum(0)))
    transmittance = torch.exp(prefix[:-1] - prefix[starts[pixels]])
    return gids, pixels, (alpha * transmittance).float()
