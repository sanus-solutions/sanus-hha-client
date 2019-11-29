import RPi.GPIO as GPIO
import time
import queue
import threading
import random
import logging
import sys, os, requests, json, picamera, io
from PIL import Image
import base64
import numpy as np
import datetime
import pymongo
import configparser

client = pymongo.MongoClient("mongodb://192.168.1.101:27017/")

# access the collection
collection = client.kidsrkids.b35

new_docs = [
	{
		"node_id" : "0",
		"unit": "None",
		"room_number": "Pilot",
		"department": "None"
	}, {

		"staff_id": "00001",
		"name": "luka",
		"title": "admin",
		"department": "None",
		"unit": "None",
	}, {

		"staff_id": "00002",
		"name": "klaus",
		"title": "admin",
		"department": "None",
		"unit": "None",
	}

]

collection.insert_many(new_docs)

print("Created new collection in MongoDB")