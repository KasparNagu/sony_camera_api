from __future__ import print_function

from pysony import SonyAPI, ControlPoint

import time
import cv2
import numpy

def liveview():
    # Connect and set-up camera
    search = ControlPoint(bindAddress="192.168.122.183")
    cameras =  search.discover(5)

    if len(cameras):
        camera = SonyAPI(QX_ADDR=cameras[0])
    else:
        print("No camera found, aborting")
        quit()

    mode = camera.getAvailableApiList()

    # some cameras need `startRecMode` before we can use liveview
    #   For those camera which doesn't require this, just comment out the following 2 lines
    if 'startRecMode' in (mode['result'])[0]:
        camera.startRecMode()
        time.sleep(2)

    sizes = camera.getLiveviewSize()
    print('Supported liveview size:', sizes)
    # url = camera.liveview("M")
    url = camera.liveview()

    lst = SonyAPI.LiveviewStreamThread(url)
    lst.setDaemon(True)
    lst.start()
    print('[i] LiveviewStreamThread started.')
    return lst.get_latest_view


if __name__ == "__main__":
    cv2.namedWindow("frame")
    handler = liveview()
    while True:
 		frame = handler()
		print(len(frame))
        	image = numpy.asarray(bytearray(frame), dtype="uint8")
		image = cv2.imdecode(image, cv2.IMREAD_COLOR)
		cv2.imshow('frame',image)
		cv2.waitKey(1)

