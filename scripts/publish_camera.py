"""Optional local/edge CCTV adapter; RTSP addresses are never fetched by the server.

EMBER_PUBLISH_TOKEN is camera-scoped, not a dashboard session. Never put it in Git.
The browser pairing exchange can also be called with httpx to obtain this token.
"""
import argparse
import os
import time
import cv2
import httpx

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server',required=True)
    parser.add_argument('--camera-id',required=True)
    parser.add_argument('--source',required=True,help='0 for local webcam, or your RTSP URL')
    parser.add_argument('--interval',type=float,default=1.0)
    args=parser.parse_args()
    if args.interval<.5:parser.error('Use interval >= 0.5 seconds')
    if not args.server.startswith('https://') and not args.server.startswith(('http://localhost:','http://127.0.0.1:')):
        parser.error('Remote transmission requires HTTPS')
    token=os.environ.get('EMBER_PUBLISH_TOKEN')
    if not token:parser.error('Set EMBER_PUBLISH_TOKEN with the camera-scoped token')
    source=int(args.source) if args.source.isdigit() else args.source
    cap=cv2.VideoCapture(source)
    if not cap.isOpened():raise RuntimeError('Camera could not be opened')
    client=httpx.Client(timeout=20,headers={'Authorization':'Bearer '+token})
    try:
        last=0
        while True:
            ok,frame=cap.read()  # Drain the capture buffer even between uploads.
            if not ok:raise RuntimeError('Camera disconnected; restart after checking the source')
            if time.monotonic()-last<args.interval:continue
            last=time.monotonic()
            h,w=frame.shape[:2]
            if w>960:frame=cv2.resize(frame,(960,round(h*960/w)))
            encoded,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,80])
            if not encoded:continue
            response=client.post(args.server.rstrip('/')+'/api/publisher/'+args.camera_id+'/frames',content=jpeg.tobytes(),headers={'Content-Type':'image/jpeg'})
            if response.status_code==429:continue
            response.raise_for_status()
            result=response.json()
            print('frame',result['latency_ms'],'ms',result['temporal']['signal'],flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        try:client.post(args.server.rstrip('/')+'/api/publisher/'+args.camera_id+'/stop')
        except httpx.HTTPError:pass
        client.close()

if __name__=='__main__':main()
