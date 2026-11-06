"""Tracked-person MiVOLO adapter with optional YuNet face detection."""
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
        import cv2
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
        face_model_path = settings.get('face_model')
        detector = None
        if face_model_path:
            face_model_path = Path(face_model_path).expanduser().resolve()
            if not face_model_path.is_file():
                raise FileNotFoundError(f'YuNet face model missing: {face_model_path}')
            detector = cv2.FaceDetectorYN.create(str(face_model_path), '', (320, 320),
                                                  score_threshold=float(settings.get('face_conf', 0.85)))
        model = MiVOLO(str(checkpoint), device=device, half=False,
                       disable_faces=detector is None, use_persons=True)
        if not model.meta.use_person_crops:
            raise ValueError('A face+body checkpoint is required, not a face-only checkpoint.')

        def predict_age(crop):
            h, w = crop.shape[:2]
            boxes_data = [[0, 0, w, h, 1.0, 0]]
            face_valid = False
            if detector is not None:
                detector.setInputSize((w, h))
                _, faces = detector.detect(crop)
                if faces is not None:
                    # Only a sufficiently large face in the upper part of this tracked body.
                    min_width = int(settings.get('min_face_width', 64))
                    candidates = [f for f in faces if f[2] >= min_width and f[3] >= min_width
                                  and f[1] + f[3] / 2 < h * 0.65]
                    if candidates:
                        f = max(candidates, key=lambda item: float(item[2] * item[3] * item[-1]))
                        x, y, fw, fh = map(float, f[:4])
                        x1, y1, x2, y2 = max(0, int(x)), max(0, int(y)), min(w, int(x + fw)), min(h, int(y + fh))
                        face = crop[y1:y2, x1:x2]
                        blur = cv2.Laplacian(cv2.cvtColor(face, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() if face.size else 0
                        if blur >= float(settings.get('min_face_sharpness', 35)):
                            boxes_data.append([x1, y1, x2, y2, float(f[-1]), 1])
                            face_valid = True
            if detector is not None and not face_valid and settings.get('require_face', True):
                return None, 'face-unavailable'
            boxes = torch.tensor(boxes_data, dtype=torch.float32)
            detection = Results(orig_img=crop, path='tracked-person',
                                names={0: 'person', 1: 'face'}, boxes=boxes)
            prediction = PersonAndFaceResult(detection)
            # Official predict handles missing face, normalization and age scaling.
            model.predict(crop, prediction)
            return prediction.ages[0], ('face-body' if face_valid else 'body-only')

        # Exercise the actual body-only path before reporting ready.
        predict_age(np.full((256, 128, 3), 127, dtype=np.uint8))
        print(f'[Age/MiVOLO] Ready | face={detector is not None} | device={device}', flush=True)
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
                    value, mode = predict_age(crop)
                    if value is not None and math.isfinite(float(value)) and 0 <= float(value) <= 100:
                        reply.update(age=float(value), reason=mode)
                    else:
                        reply['reason'] = mode if value is None else 'invalid-age'
        except Exception as exc:
            reply['reason'] = 'analysis-error'
            print(f'[Age/MiVOLO Loop Error] {type(exc).__name__}: {exc}', flush=True)
        reply['ms'] = (time.monotonic() - start) * 1000
        replies.put(reply)


