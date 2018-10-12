import requests
import numpy as np
import base64
import ast
import argparse
import os
from PIL import Image

ADD_FACE_URL = 'http://192.168.0.106:5000/sanushost/api/v1.0/add_face'
# TODO laad image here

def add_images_dir(path_to_scan):
    while len(os.listdir(path_to_scan)) != 0:
        for item in os.listdir(path_to_scan):
            dirpath = os.path.join(path_to_scan, item)
            if os.path.isfile(dirpath):
                face_id = item.split('.')[0]
                ret = add_image(dirpath, face_id)
                if ret.json()['Status'] == 'success':
                    os.remove(dirpath)

def add_image(filename, face_id):
    image = np.asarray(Image.open(filename), dtype=np.uint8)
    shape_string = str(image.shape)
    image = image.astype(np.float64)
    img_64 = base64.b64encode(image).decode('ascii')
    payload = {"Image": img_64, "Shape": shape_string, "ID": face_id}
    headers = {"Content-Type": "application/json", "Accept": "text/plain"}
    result = requests.post(ADD_FACE_URL, json=payload, headers=headers)
    return result


parser = argparse.ArgumentParser(description='Adding face to face collection')
parser.add_argument('path_to_scan', type=str, help='path of directory to scan')
args = parser.parse_args()

add_images_dir(args.path_to_scan)
