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
collection = client.test.jhm

new_docs = [
	{
		"NodeID" : "0",
		"Unit": "ICU",
		"RoomNumber": "25A",
		"Department": "Oncology"
	}, {

		"StaffID": "234B",
		"Name": "luka",
		"Title": "nurse",
		"Department": "Oncology",
		"Unit": "None",
	}

]

collection.insert_many(new_docs)

print("Created new collection in MongoDB")