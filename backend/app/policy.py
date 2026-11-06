"""Conservative two-stage fire filtering for image frames.

Apply AFTER YOLO prediction at conf=.05, NMS IoU=.7, rect=False, imgsz=640.
Preserve smoke at its existing .25 threshold. Smoke never creates a fire box;
it may only support an existing low-confidence fire prediction.
"""
from __future__ import annotations

def box_iou(a, b):
    intersection = max(0., min(a[2], b[2])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[1], b[1]))
    area_a = max(0., a[2]-a[0])*max(0., a[3]-a[1])
    area_b = max(0., b[2]-b[0])*max(0., b[3]-b[1])
    union = area_a + area_b - intersection
    return intersection/union if union > 0 else 0.


def filter_predictions(predictions, policy, shape):
    """Return original indices; no invented/merged boxes or class relabeling."""
    strong_conf = policy.get('strong_conf', .25)
    weak_conf = policy.get('weak_conf', strong_conf)
    if not 0 < weak_conf <= strong_conf < 1:
        raise ValueError('Require 0 < weak_conf <= strong_conf < 1')
    duplicate_iou = policy.get('duplicate_iou', .7)
    if not 0 < duplicate_iou <= 1:
        raise ValueError('Invalid duplicate IoU')
    weak_support = policy.get('weak_support', 'none')
    if weak_support not in ('none', 'image_strong_fire', 'near_strong_fire', 'fire_or_smoke'):
        raise ValueError('Unsupported weak support')
    strong = [p for p in predictions if p['class_id'] == 1 and p['score'] >= strong_conf]
    smoke = [p for p in predictions if p['class_id'] == 0 and p['score'] >= policy.get('support_smoke_conf', .5)]
    selected = []
    h, w = shape
    for index, pred in enumerate(predictions):
        if pred['class_id'] == 0:
            if pred['score'] >= policy.get('smoke_conf', .25):
                selected.append(index)
            continue
        if pred['class_id'] != 1 or pred['score'] < weak_conf:
            continue
        if pred['score'] < strong_conf:
            if weak_support not in ('none', 'fire_or_smoke') and not strong:
                continue
            if weak_support in ('near_strong_fire', 'fire_or_smoke'):
                a = pred['xyxy']
                near = False
                for other in strong:
                    b = other['xyxy']
                    dx = ((a[0]+a[2])-(b[0]+b[2])) / (2*w)
                    dy = ((a[1]+a[3])-(b[1]+b[3])) / (2*h)
                    if (dx*dx + dy*dy)**.5 <= policy.get('support_radius', .25):
                        near = True
                        break
                if not near and weak_support == 'fire_or_smoke':
                    area = max(0., a[2]-a[0])*max(0., a[3]-a[1])
                    for other in smoke:
                        b = other['xyxy']
                        intersection = max(0., min(a[2], b[2])-max(a[0], b[0])) * max(
                            0., min(a[3], b[3])-max(a[1], b[1]))
                        if area > 0 and intersection/area >= policy.get('support_smoke_coverage', .5):
                            near = True
                            break
                if not near:
                    continue
        selected.append(index)
    # Stable confidence-ordered, class-specific extra suppression. This is not
    # equivalent to rerunning YOLO with a lower NMS IoU; keep raw YOLO IoU=.7.
    fire = sorted((i for i in selected if predictions[i]['class_id'] == 1),
                  key=lambda i: (-predictions[i]['score'], i))
    kept = []
    for index in fire:
        if all(box_iou(predictions[index]['xyxy'], predictions[k]['xyxy']) <= duplicate_iou for k in kept):
            kept.append(index)
    return sorted(kept + [i for i in selected if predictions[i]['class_id'] == 0])


def refine_predictions(predictions, indices, refinement=None):
    """Optional localization only: preserve labels, scores, count and candidates.

    Average overlapping same-class raw proposals, then conservatively blend with
    the selected box. No label data or smoke-to-fire relabeling is used.
    """
    if not refinement:
        return [dict(predictions[i], xyxy=list(predictions[i]['xyxy'])) for i in indices]
    import math
    alpha = float(refinement['alpha'])
    overlap = float(refinement['iou_threshold'])
    minimum = float(refinement['min_score'])
    ratio = float(refinement.get('score_ratio', .5))
    classes = refinement.get('class_ids', [1])
    if (not all(math.isfinite(v) for v in [alpha, overlap, minimum, ratio]) or
        not 0 <= alpha <= 1 or not 0 < overlap <= 1 or not 0 <= minimum <= 1 or
        not 0 <= ratio <= 1 or classes != [1]):
        raise ValueError('Unsupported localization refinement parameters')
    output = []
    for index in indices:
        original = predictions[index]
        pred = dict(original, xyxy=list(original['xyxy']))
        if pred['class_id'] in classes:
            peers = [q for q in predictions if q['class_id'] == pred['class_id']
                     and q['score'] >= max(minimum, pred['score'] * ratio)
                     and box_iou(pred['xyxy'], q['xyxy']) >= overlap]
            if len(peers) > 1:
                weights = [q['score'] ** 2 for q in peers]
                denominator = sum(weights)
                average = [sum(q['xyxy'][j] * w for q, w in zip(peers, weights)) / denominator
                           for j in range(4)]
                pred['xyxy'] = [(1-alpha)*x + alpha*y for x, y in zip(pred['xyxy'], average)]
        output.append(pred)
    return output
