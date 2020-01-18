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

		"staff_id": "00003",
		"name": "Ray",
		"title": "admin",
		"department": "None",
		"unit": "None",
	}, {

		"staff_id": "00004",
		"name": "Stephanie",
		"title": "admin",
		"department": "None",
		"unit": "None",
	}, {

		"staff_id": "00005",
		"name": "Jennifer",
		"title": "admin",
		"department": "None",
		"unit": "None",
	}, {

		"staff_id": "00006",
		"name": "Heather",
		"title": "admin",
		"department": "None",
		"unit": "None",
	}, {

		"staff_id": "00007",
		"name": "Tajuana",
		"title": "admin",
		"department": "None",
		"unit": "None",
	}, {

		"staff_id": "00008",
		"name": "Michelle",
		"title": "staff",
		"department": "None",
		"unit": "None",
	}, {

		"staff_id": "00009",
		"name": "Summer",
		"title": "staff",
		"department": "None",
		"unit": "None",
	}

]

collection.insert_many(new_docs)

print("Created new collection in MongoDB")
