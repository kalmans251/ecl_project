"""MiVOLO v1 body-only adapter from the project's previous CCTV analyzer."""
import math
import queue
import time

def age_worker(jobs, replies, stop, settings):
    """MiVOLO v1 body-only inference; retain main-process ByteTrack identity."""
    try:
        import sys
        from pathlib import Path
        repo = settings.get('repo')
        if repo:
            root = Path(repo).expanduser().resolve()
            if not (root / 'mivolo' / 'model' / 'mi_volo.py').is_file():
                raise FileNotFoundError(f'Invalid MiVOLO repository: {root}')
            sys.path.insert(0, str(root))
        import numpy as np
        import torch
        from ultralytics.engine.results import Results
        from mivolo.model.mi_volo import MiVOLO
        from mivolo.structures import PersonAndFaceResult

        torch.set_num_threads(2)
        device = settings['device']
        if device == 'auto':
            device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
        elif str(device).isdigit():
            device = f'cuda:{device}'
        checkpoint = Path(settings['checkpoint']).expanduser().resolve()
        if not checkpoint.is_file():
            raise FileNotFoundError(f'MiVOLO face+body v1 checkpoint missing: {checkpoint}')
        model = MiVOLO(str(checkpoint), device=device, half=False,
                       disable_faces=True, use_persons=True)
        if not model.meta.use_person_crops:
            raise ValueError('A face+body checkpoint is required, not a face-only checkpoint.')

        def predict_age(crop):
            h, w = crop.shape[:2]
            # The crop is already one tracked person. Do not re-detect or change IDs.
            # MiVOLO requires both class names even when no face boxes are supplied.
            boxes = torch.tensor([[0, 0, w, h, 1.0, 0]], dtype=torch.float32)
            detection = Results(orig_img=crop, path='tracked-person',
                                names={0: 'person', 1: 'face'}, boxes=boxes)
            prediction = PersonAndFaceResult(detection)
            # Official predict handles missing face, normalization and age scaling.
            model.predict(crop, prediction)
            return prediction.ages[0]

        # Exercise the actual body-only path before reporting ready.
        predict_age(np.full((256, 128, 3), 127, dtype=np.uint8))
        print(f'[Age/MiVOLO] Ready | body-only | device={device}', flush=True)
        replies.put(dict(kind='ready'))
    except Exception as exc:
        print(f'[Age/MiVOLO Init Error] {type(exc).__name__}: {exc}', flush=True)
        replies.put(dict(kind='fatal', message=f'{type(exc).__name__}: {exc}'))
        return

    while not stop.is_set():
        try:
            job = jobs.get(timeout=0.25)
        except queue.Empty:
            continue
        if job is None:
            break
        reply = {k: job[k] for k in ('id', 'token', 'captured')}
        reply.update(kind='result', age=None, reason='eval-failed')
        start = time.monotonic()
        try:
            if start - job['captured'] > 3:
                reply['reason'] = 'stale-job'
            else:
                crop = job['crop']
                if crop.shape[0] < 64 or crop.shape[1] < 32:
                    reply['reason'] = 'too-small'
                else:
                    value = predict_age(crop)
                    if value is not None and math.isfinite(float(value)) and 0 <= float(value) <= 100:
                        reply.update(age=float(value), reason='body-only')
                    else:
                        reply['reason'] = 'invalid-age'
        except Exception as exc:
            reply['reason'] = 'analysis-error'
            print(f'[Age/MiVOLO Loop Error] {type(exc).__name__}: {exc}', flush=True)
        reply['ms'] = (time.monotonic() - start) * 1000
        replies.put(reply)


