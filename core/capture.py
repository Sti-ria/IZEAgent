import cv2
import mss
import numpy as np


class PVZCapture:
    """
    截取 PVZ 客户区。
    """

    def __init__(self, region):
        self.region = {
            "left": int(region["left"]),
            "top": int(region["top"]),
            "width": int(region["width"]),
            "height": int(region["height"]),
        }
        self.sct = mss.mss()

    def update_region(self, region):
        self.region = {
            "left": int(region["left"]),
            "top": int(region["top"]),
            "width": int(region["width"]),
            "height": int(region["height"]),
        }

    def grab(self):
        img = np.array(self.sct.grab(self.region))
        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return frame
