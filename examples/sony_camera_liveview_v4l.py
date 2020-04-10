from __future__ import print_function

from pysony import SonyAPI, ControlPoint

import time
import v4l2
import cv2
import numpy
import fcntl
import os
import sys

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

    sizes = camera.getLiveviewSize()
    print('Supported liveview size:', sizes)
    # url = camera.liveview("M")
    url = camera.liveview()

    lst = SonyAPI.LiveviewStreamThread(url)
    lst.setDaemon(True)
    lst.start()
    print('[i] LiveviewStreamThread started.')
    return lst.get_latest_view

class V4l2Writer:
	def __init__(self,deviceName):
		self.deviceName = deviceName
		self.device = None
		self.width = 0
		self.height = 0
		self.isRgb = False
	def init(self,width,height):
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
        	self.buffer = numpy.zeros((format.fmt.pix.height, 2*format.fmt.pix.width), dtype=numpy.uint8)
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
if __name__ == "__main__":
    v4l2w = V4l2Writer('/dev/video2')
    handler = liveview(sys.argv[1] if len(sys.argv)>1 else None)
    while True:
 		frame = handler()
               	image = numpy.asarray(bytearray(frame), dtype="uint8")
		image = cv2.imdecode(image, cv2.IMREAD_COLOR)
		v4l2w.write(image)
