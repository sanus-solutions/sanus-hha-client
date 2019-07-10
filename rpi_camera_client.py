"""
    Author: Luka Antolic-Soban
"""
import RPi.GPIO as GPIO
import time
import queue
import threading
import random
import sys, os, requests, time, json, picamera, io
from PIL import Image
import base64
import numpy as np
import datetime
import boto3
import pymongo
import configparser
from sanus_cloud_services import CloudServices

"""
	Class to encapsulate the Raspberry Pi IoT device that will be attached to the doorways of hospital patient rooms.
"""
class PiClient:

    def __init__(self):

        config = configparser.ConfigParser()
        config.read('config.ini')
        
        ### Initialize config values
        self.ClientType = config['PROPERTIES']['ClientType']
        self.NODE_ID = config['PROPERTIES']['NodeID']
        # Time delay for alert sent in seconds
        self.ALERT_TIME_DELAY = config['PROPERTIES']['AlertTimeDelay']
        # Server info
        SERVER_HOST = config['LOCALSERVER']['ServerHost']
        SERVER_PORT = config['LOCALSERVER']['ServerPort']
        # API Endpoints
        API_PostEntryImg = config['LOCALSERVER']['API_EntryImg']
        API_PostDruidData = config['DRUID']['API_PostDruidData']
        API_PostDruidQuery = config['DRUID']['API_PostDruidQuery']
        # Druid
        DRUID_SERVER_HOST = config['DRUID']['DruidServerHost']
        DRUID_SERVER_PORT_DATA = config['DRUID']['DruidServerPortData']
        DRUID_SERVER_PORT_QUERY = config['DRUID']['DruidServerPortQuery']
        self.DRUID_SERVER_HEADERS = {'Content_Type': 'application/json'}
        # Cloud Services
        MONGO_STRING = config['CLOUDSERVER']['MongoClient']
        # Camera
        self.CAMERA_WIDTH = int(config['CAMERA']['Width'])
        self.CAMERA_HEIGHT = int(config['CAMERA']['Height'])
        self.CAMERA_CHANNELS = int(config['CAMERA']['Channels'])
        self.CAMERA_SHAPE = config['CAMERA']['Shape']


        ### END CONFIG ###

        # Local Inits

        # GPIO pins initialization for PIR sensor
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(11, GPIO.IN)

        # Camera Init
        self.camera = picamera.PiCamera()
        self.camera.resolution = (self.CAMERA_WIDTH, self.CAMERA_HEIGHT)
        self.camera.start_preview(fullscreen=False, window=(100, 20, 0, 0))
        time.sleep(2)

        # Camera Delay
        self.isSensorInDelayMode = False

        # Entry Queues
        # pqueue is for receiving the timestamps and payload (image capture)
        # msgqueue is for receiving the timestamps and payload for the 2nd post request to check if an alert needs to be sent to the staff member
        self.pqueue = queue.PriorityQueue()
        self.msgqueue = queue.PriorityQueue()
        self.welcomequeue = queue.Queue()

        # StaffID list
        self.staffIDList = {}

        # List of unsuccessful Druid Events
        self.failedEventsList = []

        # Image place holders
        self.shape = self.CAMERA_SHAPE
        self.image = np.empty(( int(self.CAMERA_HEIGHT), int(self.CAMERA_WIDTH), int(self.CAMERA_CHANNELS) ), dtype=np.uint8)

        # API URLs
        self.postEntryImg = 'http://' + SERVER_HOST + ':' + SERVER_PORT + API_PostEntryImg

        # API Druid
        self.postData = 'http://' + DRUID_SERVER_HOST + ':' + DRUID_SERVER_PORT_DATA + API_PostDruidData
        self.postQuery = 'http://' + DRUID_SERVER_HOST + ':' + DRUID_SERVER_PORT_QUERY + API_PostDruidQuery

        # Cloud Services
        self.cloudServices = CloudServices.CloudServices()

        # MongoDB
        self.mongo = pymongo.MongoClient(MONGO_STRING)
        

    # Function to take image from the camera and then sends it to be processed
    # Input: None
    # Returns: None
    def captureImage(self, client):
        # Initial timestamp of image capture
        timestamp = time.time()

        # Take a picture, then send that picture to the HTTP thread
        img = np.empty(( self.CAMERA_HEIGHT, self.CAMERA_WIDTH, self.CAMERA_CHANNELS), dtype=np.uint8)
        client.camera.capture(img, 'rgb')

        image_temp = img.astype(np.float64)
        image_64 = base64.b64encode(image_temp).decode('ascii')

        client.prepare_and_process(client.NODE_ID, timestamp, image_64, client.shape)

    # Function to send raw data to druid server
    # Returns: NONE
    def send_druid_data(self, type, nodeID, staffID, staff_title, unit, room_number, response_type, response_message):
        time = datetime.datetime.utcnow().isoformat()

        payload = {
            'time': time,
            'type': type,
            'nodeID': nodeID,
            'staffID': staffID,
            'staff_title': staff_title,
            'unit': unit,
            'room_number': room_number,
            'response_type': response_type,
            'response_message': response_message
        }

        try:
            result = requests.post(self.postData, json=payload, headers=self.DRUID_SERVER_HEADERS)

            # If druid connection is healthy, then check if there are any failedEvents to send up as well
            if(len(self.failedEventsList) > 0):
                print("sending failed event to druid")
                for event in self.failedEventsList:
                    result = requests.post(self.postData, json=event, headers=self.DRUID_SERVER_HEADERS)
                self.failedEventsList.clear()

        except:
            # Save the result for later
            self.failedEventsList.append(payload)


    # Function to play .wav files to welcome staff members.
    # Returns : NONE
    def send_welcome(self, name):

        if name == "clean":
            os.system("aplay -q cleanA.wav")
        else:
            os.system("aplay -q " + name + "W.wav")

        time.sleep(1)

    # Function to play .wav files to alert staff members.
    # Returns : NONE
    def send_alert(self, name):
        os.system("aplay -q " + name + "A.wav")

        print(name + " is not clean")
        time.sleep(1)

    # Peeks at head of pqueue.
    # Returns: The timestamp as the key associated with the tuple.
    def peek_timestamp_at_head(self):
        if(not self.pqueue.empty()):
            return self.pqueue.queue[0][0]
        else:
            return -1

    # Peeks at head of msgqueue
    # Returns: The timestamp as the key associated with the tuple.
    def peek_timestamp_at_alert(self):
        if(not self.msgqueue.empty()):
            return self.msgqueue.queue[0][0]
        else:
            return -1

    # Function that grabs the 4 necessary parts of the post request to tensorflow server and places them as a tuple in the pqueue
    # Node ID, Timestamp of first image capture, buffer for image, and size of the image
    # Returns: NONE
    def prepare_and_process(self, NODE_ID, timestamp, img_buffer, img_size):
        payload = {'NodeID': NODE_ID, 'Timestamp': timestamp, 'Image': img_buffer, 'Shape': img_size}
        headers = {'Content_Type': 'application/json', 'Accept': 'text/plain'}

        # the timestamp, payload, and header will be saved so that we can make another post request to determine HH status
        client.pqueue.put((timestamp, payload, headers))

    # Thread that is created once a request is to be sent and then deleted after that request
    def http_thread(self, timestamp, payload, headers):

        # Init request variable for responses
        result = None

        # Send post request to the server
        try:
            result = requests.post(self.postEntryImg, json=payload, headers=headers)
            print("Returned this from Server: " + str(result))
            result = result.json()
            print("Someone entered the room and this was returned: " + str(result))
        except requests.exceptions.Timeout:
            print("Timeout due to unreliable server connection - dropping image")
            return
        except Exception as e:
            print(e)
            return


        # Returns a List of Dictionaries like [{'StaffID': None, 'Status': 'no face'}]
        for i in range(len(result['Result'])):

            resultName = result['Result'][i][0]
            resultIsClean = result['Result'][i][1]
            
            # If no face was found on Recognition or TF server, then get out of this thread and drop
            # the images.
            if(result['Face'] == 0 or resultName == None):
                return

            # Check here to see if the staffID has been seen in the last 30 seconds (to mitigate
            # multiple alerts given out)
            # If the staffID has NOT been seen, add it to pqueue, if it has YES, then stop this task and continue
            if(resultName != None and self.staff_checker(resultName) == 0):
                # add the staffID and timestamp kv pair to list
                self.staffIDList[resultName] = time.time()
                print("adding staff name to 'seen' list")
            else:
                return

            # Check the status of the staff member. There will always be a welcome message sent here.
            # Once the welcome message is sent to the audio device, the payload will be placed in the msqueue to
            # be sent later to see if a further alert is needed.

            # Get data from MongoDB on that particular staff member
            collection = self.mongo.development.hospital1
            staffDoc = collection.find_one({"staff_id": resultName})
            nodDoc = collection.find_one({"node_id": self.NODE_ID })

             # Druid data schema : type, nodeID, staffID, staff_title, unit, room_number, response_type, response_message
            if(resultIsClean == False):
                self.send_druid_data("Entry", nodDoc["node_id"], staffDoc["staff_id"], staffDoc["staff_title"], nodDoc["node_unit"], nodDoc["node_roomNum"], "Entry", "Not clean")
                self.welcomequeue.put(resultName)
            elif(resultIsClean == True):
                self.send_druid_data("Entry", nodDoc["node_id"], staffDoc["staff_id"], staffDoc["staff_title"], nodDoc["node_unit"], nodDoc["node_roomNum"], "Entry", "Clean")
                self.welcomequeue.put(resultName)
                return

        # Determine the hygiene status of the staff member, if there is a staff member face and they are not on dispenser list
        self.msgqueue.put(((timestamp + float(self.ALERT_TIME_DELAY)), payload, headers))


    # Thread that will run in a loop that will constantly check in the pqueue for any payloads that need to be processed and sent to the server
    def control_thread(self): # always running on startup

        #Create new list and timestamp for payload
        images = []
        timestamp = None
        payload = None
        headers = None

        while(True):

            # Wait until the sensor is not in delay mode and is not triggered
            if(GPIO.input(11) == 0 and self.isSensorInDelayMode == False and not self.pqueue.empty()):


                print("Sending images to server! Size of the queue is: " + str(self.pqueue.qsize()))

                # Then loop through them all and put them in the image list
                while(not self.pqueue.empty()):
                    # Dequeue to get the first preprocessed image
                    tstamp, pload, hder = self.pqueue.get()

                    if(timestamp == None):
                        # Add the first image timestamp
                        timestamp = tstamp
                        payload = pload
                        headers = hder

                    #images.append(payload['Image'])
        
                # Add the 5+ images to the payload
                #payload['Image'] = images

                # Create an HTTP thread for just this request
                # send to HTTP thread
                http_thread = threading.Thread(kwargs={'timestamp': timestamp, 'payload': payload, 'headers': headers}, target=client.http_thread)
                http_thread.daemon = True
                http_thread.start()

                # Clear everything to free up space for next batch
                images = []
                timestamp = None
                payload = None
                headers = None



    # Thread that will constantly run on startup and only grab jobs from msgqueue that need to be sent
    # to the server to determine if a second alert needs to be sent to a staff member
    def alert_thread(self):
        while(True):

            # First check and see if we need to send welcome alerts to anyone who came into the room
            if(not self.welcomequeue.empty()):
                self.send_welcome(self.welcomequeue.get())

            # Check queue to see if it has passed ALERT_TIME_DELAY secs from current time.
            # We should only alert when this time threshold has passed to give the staff member
            # time to conduct hand hygiene.
            if(self.peek_timestamp_at_alert() == -1):
                continue
            elif(self.peek_timestamp_at_alert() - time.time() <= 0.0):

                # Dequeue head and then keep dequeuing until head is 1 second later than earliest timestamp
                # Now that 30 sec have past, we need to check and see if they have actually washed their hands in that time-frame
                timestamp, payload, headers = self.msgqueue.get()


                print("Sending check to see if they washed hands")

                # Send second post request again and check result (see if staff member has
                # used a hand hygiene device yet.)
                # If there is a face, and it is staff, and they are still not in the dispenser list, send an alert to them
                payload["Timestamp"] = time.time()

                result = None
                try:
                    result = requests.post(self.postEntryImg, json=payload, headers=headers)
                except requests.exceptions.Timeout:
                    print("Timeout due to unreliable server connection - dropping image")
                    continue
                except:
                    print("Tensorflow server unreachable, will save alert for later")
                    continue

                # When the server returns STATUS and NAME of staff member.
                # Send an alert accordingly.
                result = result.json()
                print(result)

                # MongoDB
                collection = self.mongo.development.hospital1

                # Returns a List of Dictionaries like [{'StaffID': None, 'Status': 'no face'}]
                for i in range(len(result['Result'])):

                    resultName = result['Result'][i][0]
                    resultIsClean = result['Result'][i][1]

                    staffDoc = collection.find_one({"staff_id": resultName })
                    nodDoc = collection.find_one({"node_id": self.NODE_ID })


                    ## If we get "Status" = True message then that means that the staff member has breached protocol and not washed
                    ## their hands within the 20 second period. If "Status" = False the staff member is clean and has used a soap dispenser within
                    ## the alloted timeframe

                    if(resultIsClean == False):
                        self.send_druid_data("Alert", nodDoc["node_id"], staffDoc['staff_id'], staffDoc['staff_title'], nodDoc["node_unit"], nodDoc["node_roomNum"], "Alert", "Alert given")
                        self.send_alert(staffDoc['staff_id'])

                        # Send SMS to staff member from AWS
                        self.cloudServices.simple_notification_service(staffDoc["staff_phoneNum"], staffDoc['staff_id'].capitalize() + ", you forgot to wash your hands, please do so.")
                        
                    elif(resultIsClean == True):
                        self.send_druid_data("Alert", nodDoc["node_id"], staffDoc['staff_id'], staffDoc['staff_title'], nodDoc["node_unit"], nodDoc["node_roomNum"], "Alert", "No alert")
                        self.send_alert("clean")


    # #### MIGHT BE REMOVED IN FUTURE RELEASE ####
    # Issues arise when a the camera unit takes multiple images of a user at once. This allows multiple alerts to be given for only 1 instance
    # of a breach. To counteract this, this  will constantly look at users that have had pictures taken in the last 30 secounds so that
    # a staff member cannot be given multiple alerts
    # Returns: 0 if it is cleared for the staffID to get an alert
    #          1 if the staffID should not get an alert
    def staff_checker(self, staffID):

        if(self.staffIDList.get(staffID) == None):
            # Staff not in list so we are good to give an alert
            return 0

        if(time.time() - self.staffIDList.get(staffID) > 30.0):
            # check timestamps to see if there is at least a 30 sec difference between them
            # if so, we are good to give an alert
            return 0
        else:
            # if the time delay is not long enough, disregard this event as there should be NO ALERT
            return 1



#### MAIN ####
if __name__ == '__main__':
    client = PiClient()

    # Create/Initiate threads
    control_thread = threading.Thread(name='control_thread', target=client.control_thread)
    alert_thread = threading.Thread(name='alert_thread', target=client.alert_thread)
    control_thread.daemon = True
    alert_thread.daemon = True
    control_thread.start()
    alert_thread.start()

    # sensor delay counter
    client.isSensorInDelayMode = False

    ##### TEST
    isItOn = True
    #####

    # Main loop for IoT Device
    while(True):

        if isItOn: # If the PIR sensor is giving a HIGH signal

            client.captureImage(client)

            # Sleep due to sensor delay time
            time.sleep(0.5)

            client.isSensorInDelayMode = True
            isItOn = False


        # Check if signal on low delay and take 3 more pictures
        # Yes I repeat code here - will make function for this later.
        elif isItOn==False and client.isSensorInDelayMode == True:

            for x in range(3):

                    print("taking photo in delay mode")

                    client.captureImage(client)

                    # Take 1 photo every second for 3 seconds in delay mode
                    time.sleep(1)

            client.isSensorInDelayMode = False
