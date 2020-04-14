from __future__ import print_function

from pysony import SonyAPI, ControlPoint

import time
import cv2
import numpy
import sys
import threading

def liveview(bindAddress=None):
    # Connect and set-up camera
    search = ControlPoint(bindAddress=bindAddress)
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

    sizes = camera.getSupportedLiveviewSize();
    print('Supported liveview size:', sizes)
    sizes = camera.getAvailableLiveviewSize();
    print('Available liveview size:', sizes)
    # url = camera.liveview("M")
    url = camera.liveview()

    lst = SonyAPI.LiveviewStreamThread(url)
    lst.setDaemon(True)
    lst.start()
    print('[i] LiveviewStreamThread started.')
    return lst.get_latest_view,camera

class AFThread:
	def __init__(self,camera):
		self.camera = camera
		self.size = (0,0)
		self.running = True
		self.nextPosition = None
		self.positionCondition = threading.Condition()
	def updateSize(self,size):
		self.size = size
	def start(self):
		self.thread = threading.Thread(target=self.run)
		self.thread.setDaemon(True)
		self.thread.start()
	def updateAF(self,x,y):
		with self.positionCondition:
			self.nextPosition = (x,y)
			self.positionCondition.notify()

	def run(self):
		while self.running:
			curAFPos = None
			with self.positionCondition:
				while self.nextPosition is None:
					self.positionCondition.wait()
				curAFPos = self.nextPosition
				self.nextPosition = None
			x,y = curAFPos
			xx = 100.0*x/self.size[1]
			yy = 100.0*y/self.size[0]

			ret = self.camera.setTouchAFPosition(param=[xx,yy])
			print("setTouchAFPosition(param=[%0.3g%%,%0.3g%%])=%s" % (xx,yy,str(ret)))


if __name__ == "__main__":
    cv2.namedWindow("frame")

    handler,camera = liveview(sys.argv[1] if len(sys.argv)>1 else None)
    size = [0,0]
    afThread = AFThread(camera)
    afThread.start()
    def cv2click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
		afThread.updateAF(x,y)
    cv2.setMouseCallback("frame", cv2click)
    while True:
 		frame = handler()
        	image = numpy.asarray(bytearray(frame), dtype="uint8")
		image = cv2.imdecode(image, cv2.IMREAD_COLOR)
		cv2.imshow('frame',image)
		afThread.updateSize(image.shape)
		cv2.waitKey(1)

