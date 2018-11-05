import requests, argparse, os

ADD_FACE_URL = 'http://localhost:5000/sanushost/api/v1.0/remove_face'

def remove_image(name):
    payload = {"ID" : name}
    headers = {"Content-Type": "application/json", "Accept": "text/plain"}
    result = requests.post(ADD_FACE_URL, json=payload, headers=headers)
    return result

parser = argparse.ArgumentParser(description='Removing face to face collection')
parser.add_argument('name', type=str, help='path of directory to scan')
args = parser.parse_args()

print  remove_image(args.name).json()
