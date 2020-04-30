from __future__ import print_function

from pysony import SonyAPI, ControlPoint

import time
import cv2
import numpy
import sys
import threading
import fcntl
import os
import datetime

def liveview(bindAddress=None, size=None):
    # Connect and set-up camera
    search = ControlPoint(bindAddress=bindAddress)
    cameras =  search.discover(5)

    if len(cameras):
        camera = SonyAPI(QX_ADDR=cameras[0])
    else:
        print("No camera found, aborting")
        quit()

    if not size is None:
    	sizes = camera.getSupportedLiveviewSize();
    	print('Supported liveview size:', sizes)
    	sizes = camera.getAvailableLiveviewSize();
    	print('Available liveview size:', sizes)
    	if 'result' in sizes and not size in sizes['result']:
    		print("try stopping liveview")
    		camera.stopLiveview()


    mode = camera.getAvailableApiList()

    # some cameras need `startRecMode` before we can use liveview
    #   For those camera which doesn't require this, just comment out the following 2 lines
    if 'startRecMode' in (mode['result'])[0]:
        camera.startRecMode()
        time.sleep(2)

    if not size is None:
       url = camera.liveview(size)
    else:
       url = camera.liveview()

    lst = SonyAPI.LiveviewStreamThread(url)
    lst.setDaemon(True)
    lst.start()
    print('[i] LiveviewStreamThread started.')
    return lst.get_latest_view,camera

class V4l2Writer:
	def __init__(self,deviceName):
		self.deviceName = deviceName
		self.device = None
		self.width = 0
		self.height = 0
		self.isRgb = False
	def init(self,width,height):
		import v4l2
		if self.width == width and self.height == height:
			return
		if not self.device is None:
			self.device.close()
		self.device = os.open(self.deviceName, os.O_WRONLY | os.O_SYNC)
		print("Initializing %s width=%d height=%d fn=%s" % (self.deviceName,width,height,self.device))
		self.width = width
		self.height = height
		capability = v4l2.v4l2_capability()
		fcntl.ioctl(self.device, v4l2.VIDIOC_QUERYCAP, capability)
		print("v4l2 driver: " + capability.driver)
		format = v4l2.v4l2_format()
		format.type = v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT
		format.fmt.pix.width = width
		format.fmt.pix.height = height
		format.fmt.pix.field = v4l2.V4L2_FIELD_NONE
		if self.isRgb:
			format.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_RGB24
			format.fmt.pix.bytesperline = format.fmt.pix.width * 3
			format.fmt.pix.sizeimage = format.fmt.pix.width * format.fmt.pix.height * 3
			format.fmt.pix.colorspace =  v4l2.V4L2_COLORSPACE_SRGB

		else:
			format.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_YUYV
			format.fmt.pix.bytesperline = format.fmt.pix.width * 2
			format.fmt.pix.sizeimage = format.fmt.pix.width * format.fmt.pix.height * 2
			format.fmt.pix.colorspace = v4l2.V4L2_COLORSPACE_JPEG
		fcntl.ioctl(self.device, v4l2.VIDIOC_S_FMT, format)
		if(width != format.fmt.pix.width or height != format.fmt.pix.height):
			print("Warning: Input and v4l output dimensions missmatch: in=%dx%d v4l=%dx%d" % (
				width,height,format.fmt.pix.width,format.fmt.pix.height))
		self.buffer = numpy.zeros((height, 2*width), dtype=numpy.uint8)
#        	self.buffer = numpy.zeros((format.fmt.pix.height, 2*format.fmt.pix.width), dtype=numpy.uint8)
	def write(self,data):
		shape = data.shape
		self.init(shape[1],shape[0])
		if self.isRgb:
			dataoutbin = data.tostring()
		else:
			yuv = cv2.cvtColor(data, cv2.COLOR_BGR2YUV)
			for i in range(self.height):
				self.buffer[i,::2] = yuv[i,:,0]
				self.buffer[i,1::4] = yuv[i,::2,1]
				self.buffer[i,3::4] = yuv[i,::2,2]
			dataoutbin = self.buffer.tostring()
		os.write(self.device, dataoutbin)
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

class Status:
	def __init__(self,camera):
		self.fps = 0
		self.lastFpsUpdate = time.time()
		self.nFramesSinceUpdate = 0
		self.camera = camera
		self.lastStatusTimestamp = 0
		self.batteryLevel = 0
		self.batteryLevelDenom = 4
		self.fNumber = "NA"
		self.focusMode ="NA"
	def frame(self):
		self.nFramesSinceUpdate += 1
		if self.nFramesSinceUpdate > 5:
			curT = time.time()
			self.fps = 1.0 * self.nFramesSinceUpdate / (curT - self.lastFpsUpdate)
			self.nFramesSinceUpdate = 0
			self.lastFpsUpdate = curT
	def updateStatus(self):
		status = self.camera.getEvent(['false'])
		self.lastStatusTimestamp = time.time()
		for i in status['result']:
			if not i is None and 'type' in i:
				typ = i['type']
				if typ == "batteryInfo":
					self.batteryLevel = i['batteryInfo'][0]['levelNumer']
					self.batteryLevelDenom = i['batteryInfo'][0]['levelDenom']
					print("battery level=%d/%d" % (self.batteryLevel ,self.batteryLevelDenom))
				elif typ == "fNumber":
					self.fNumber = i['currentFNumber']
				elif typ == "focusMode":
					self.focusMode = i['currentFocusMode']
	def printStatusToImage(self,image):
		t = time.time() - self.lastStatusTimestamp
		if t < 2:
			overlay = image
		elif t < 10:
			overlay = image.copy()
		else:
			return
		cv2.putText(overlay, "%0.4g fps" % self.fps, (10,30),cv2.FONT_HERSHEY_SIMPLEX, 1, (80, 0, 0))
		w = overlay.shape[1]
		h = overlay.shape[0]
		batCol = (0,200,0) if self.batteryLevel > 0 else (0,0,200)
		cv2.putText(overlay, "BAT", (10,h-15),cv2.FONT_HERSHEY_SIMPLEX, 1, batCol)
		batQ = 25
		for i in range(0,self.batteryLevelDenom):
			cv2.rectangle(overlay,((70+i*(batQ+4)),h-13-batQ),((70+i*(batQ+4)+batQ),h-13),batCol,-1 if i < self.batteryLevel else 2)
		cv2.putText(overlay,"F%s" % self.fNumber,(w-100,30),cv2.FONT_HERSHEY_SIMPLEX, 1, (80, 0, 0))
		cv2.putText(overlay,"%s" % self.focusMode,(w-100,h-30),cv2.FONT_HERSHEY_SIMPLEX, 1, (80, 0, 0))
		if t > 2:
			alpha = 1 - (t-2)/8.
			cv2.addWeighted(overlay, alpha, image, 1 - alpha, 0, image)

class ImageOverlayer:
	def __init__(self,img):
		self.imageOrignal = cv2.imread(img,cv2.IMREAD_COLOR)
		self.imageResized = None
		self.mix = 0.5
	def resize(self,tgt):
		if not self.imageResized is None:
			tgtShape = tgt.shape
			resShape = self.imageResized.shape
			if tgtShape[0] == resShape[0] and tgtShape[1] == resShape[1]:
				return
		w = self.imageOrignal.shape[1]
                h = self.imageOrignal.shape[0]
		wtgt = tgt.shape[1]
		htgt = tgt.shape[0]

                widthResized = int(1.0*w*htgt/h)
                if widthResized > wtgt:
                        heightResized = int(1.0*h*wtgt/w)
                        widthResized = wtgt
                else:
                        heightResized = htgt
                image = cv2.resize(self.imageOrignal,(widthResized,heightResized))
                bx = (wtgt - image.shape[1])
                by = (htgt - image.shape[0])
                bx1 = bx/2
                bx2 = bx - bx1
                by1 = by/2
                by2 = by - by1
                self.imageResized = cv2.copyMakeBorder(image,by1,by2,bx1,bx2,cv2.BORDER_CONSTANT)
	def overlay(self,image):
		self.resize(image)
		return cv2.addWeighted(image,self.mix,self.imageResized,1-self.mix,0)
	def changeMix(self,offset):
		self.mix += offset
		if self.mix < 0:
			self.mix = 0
		elif self.mix > 1:
			self.mix = 1

if __name__ == "__main__":
	import argparse
	parser = argparse.ArgumentParser(description="Connects to a sony camera and streams to cv2 window and v4l. Shortcuts: q/esc=quit, m=switch focus mode, e=show info, up/down/pgup/pgdown=change aperture.",
	formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('--v4l-device',default=None,help="Stream to v4lloopback-device")
	parser.add_argument('--no-window',default=False,action='store_true',help='Do not show cv2 window')
	parser.add_argument('--bind',default=None,help="Bind brodcasting to this ip address. Usful when used with multiple network devices.")
	parser.add_argument('--window-name',default="Liveview",help="Name of the cv2 window")
	parser.add_argument('--size',default=None,help="Liveview size to specifiy, e.g M or L")
	parser.add_argument('--overlay-image',default=None,help="Image to overlay")

	args = parser.parse_args();

	if args.overlay_image is None:
		imageOverlayer = None
	else:
		imageOverlayer = ImageOverlayer(args.overlay_image)
	cv2.namedWindow(args.window_name)

	handler,camera = liveview(args.bind, args.size)
	if not args.v4l_device is None:
		v4l2w = V4l2Writer(args.v4l_device)
	else:
		v4l2w = None
	status = Status(camera)
	afThread = AFThread(camera)
	afThread.start()
	def cv2click(event, x, y, flags, param):
		if event == cv2.EVENT_LBUTTONDOWN:
			afThread.updateAF(x,y)
	if not args.no_window:
		cv2.setMouseCallback(args.window_name, cv2click)
	while True:
		frame = handler()
		image = numpy.asarray(bytearray(frame), dtype="uint8")
		image = cv2.imdecode(image, cv2.IMREAD_COLOR)
		if not imageOverlayer is None:
			image = imageOverlayer.overlay(image)
		if not v4l2w is None:
			v4l2w.write(image)
		status.frame()
		if not args.no_window:
			status.printStatusToImage(image)
			cv2.imshow(args.window_name,image)
		afThread.updateSize(image.shape)
		if not args.no_window:
			key = cv2.waitKey(1)
		else:
			key = 255
		if key & 0xFF == ord('q') or key == 27:
			break
		elif key & 0xFF == ord('m'):
			supportedFocusModes = camera.getSupportedFocusMode()
			availableFocusModes = camera.getAvailableFocusMode()
			focusMode = camera.getFocusMode()
			print("supportedFocusModes=%s availableFocusModes=%s focusMode=%s" %
				 (supportedFocusModes['result'],availableFocusModes['result'],focusMode['result']))
			if "MF" in focusMode['result']:
				print("Setting AF")
				ret = camera.setFocusMode(["AF-S"])
			else:
				print("Setting MF")
				ret = camera.setFocusMode(["MF"])
			print(ret)
		elif key & 0xFF == ord('c'):
			ret = camera.cancelTouchAFPosition()
			print(ret)
		elif key & 0xFF == ord('s'):
			cv2.imwrite("img_%s.jpg" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f"),image)
		elif key == 82 or key == 84 or key == 85 or key == 86:
			fnrs = camera.getSupportedFNumber()['result'][0]
#			fnrs = camera.getAvailableFNumber()['result'][0]
			print(fnrs)
			fn = camera.getFNumber()['result'][0]
			print("fnrs=%s fn=%s" % (fnrs,fn))
			if not fn in fnrs:
				continue
			i = fnrs.index(fn)
			if  key == 82:
				i2 = i - 1
			elif key  == 84:
				i2 = i + 1
			elif key == 85:
				i2 = i - 10
			else:
				i2 = i + 10
			if i2 < 0:
				i2 = 0
			elif i2 >= len(fnrs):
				i2 = len(fnrs) - 1
			next = fnrs[i2]
			print("next=%s" % next)
			camera.setFNumber(next)
			status.updateStatus()
			status.fNumber = next
		elif key == 81 or key == 83:
			if not imageOverlayer is None:
				imageOverlayer.changeMix(0.1 if key == 81 else -0.1)
		elif key != 255:
			print("key=%s" % key)
			status.updateStatus()


