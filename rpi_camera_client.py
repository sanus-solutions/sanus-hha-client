"""
    Author: Luka Antolic-Soban
"""
import RPi.GPIO as GPIO
import cv2
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
import boto3
import pymongo
import configparser
from sanus_cloud_services import CloudServices


try:
    config = configparser.ConfigParser()
    config.read('config.ini')
except:
    raise Exception("config.ini file missing.")

"""
	Class to encapsulate the Raspberry Pi IoT device that will be attached to the doorways of hospital patient rooms.
"""
class PiClient:

    def __init__(self):
        
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
        API_EntryStaffCheck = config['LOCALSERVER']['API_EntryStaffCheck']
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

        ## Local Inits

        ## Logging
        self.init_logger()

        ## GPIO pins initialization for PIR sensor
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(4, GPIO.IN)

        ## Camera Init
        self.camera = picamera.PiCamera()
        self.camera.resolution = (self.CAMERA_WIDTH, self.CAMERA_HEIGHT)
        self.camera.start_preview(fullscreen=False, window=(100, 20, 0, 0))
        time.sleep(2)

        ## Camera Delay
        self.isSensorInDelayMode = False

        ## Entry Queues
        # pqueue is for receiving the timestamps and payload (image capture)
        # msgqueue is for receiving the timestamps and payload for the 2nd post request to check if an alert needs to be sent to the staff member
        self.pqueue = queue.PriorityQueue()
        self.msgqueue = queue.PriorityQueue()
        self.welcomequeue = queue.Queue()

        ## StaffID list
        self.staffIDList = {}

        ## List of unsuccessful Druid Events
        self.failedEventsList = []

        ## Image place holders
        self.shape = self.CAMERA_SHAPE
        self.image = np.empty(( int(self.CAMERA_HEIGHT), int(self.CAMERA_WIDTH), int(self.CAMERA_CHANNELS) ), dtype=np.uint8)

        ## API URLs
        self.postEntryImg = 'http://' + SERVER_HOST + ':' + SERVER_PORT + API_PostEntryImg
        self.postEntryStaffCheck = 'http://' + SERVER_HOST + ':' + SERVER_PORT + API_EntryStaffCheck

        ## API Druid
        self.postData = 'http://' + DRUID_SERVER_HOST + ':' + DRUID_SERVER_PORT_DATA + API_PostDruidData
        self.postQuery = 'http://' + DRUID_SERVER_HOST + ':' + DRUID_SERVER_PORT_QUERY + API_PostDruidQuery

        # # Cloud Services
        # self.cloudServices = CloudServices.CloudServices()

        # MongoDB
        self.mongo = pymongo.MongoClient(MONGO_STRING)
    
    ## Logging Initialization    
    def init_logger(self, ):

        ## Check if Log folder exists
        if not os.path.exists("log"):
            os.makedirs("log")

        ## Get params from config file
        debugLevel = config['DEBUG']['LogLevel']

        ## Logger
        if debugLevel == 'Info':
            level = logging.INFO
        else:
            level = logging.DEBUG

        self.logger = logging.getLogger(__name__)
        logFileName = "log/Node" + self.NODE_ID + ".log"
        logging.basicConfig(filename=logFileName, level=level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Function to take image from the camera and then sends it to be processed
    # Input: None
    # Returns: None
    def captureImage(self, client):

        logging.info('Image Taken')

        # Initial timestamp of image capture
        timestamp = time.time()

        # Take a picture, then send that picture to the HTTP thread
        img = np.empty(( self.CAMERA_WIDTH, self.CAMERA_HEIGHT, self.CAMERA_CHANNELS), dtype=np.uint8)
        client.camera.capture(img, 'rgb')
        retval, buffer = cv2.imencode('.jpg', img)
        image_64 = base64.b64encode(buffer).decode('ascii')

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
            print("Staff member is clean")
        else:
            os.system("aplay -q welcome.wav")

        time.sleep(1)

    # Function to play .wav files to alert staff members.
    # Returns : NONE
    def send_alert(self, name):
        if name != "clean":
            os.system("aplay -q reminder.wav")
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
            result = result.json()
            self.logger.info("Someone entered the room and this was returned: " + str(result))
        except requests.exceptions.Timeout:
            self.logger.error("Timeout due to unreliable server connection - dropping image")
            return
        except Exception as e:
            self.logger.error("Exception is: " + str(e))
            text_file = open("log/"+str(timestamp)+".txt", "w")
            text_file.write(payload["Image"])
            text_file.close()
            return

        # If no face was found on Recognition or TF server, then get out of this thread and drop
        # the images.
        if(result['Face'] == 0):
            self.logger.info('No face found in image')
            return

        # Returns a List of Dictionaries like [{'StaffID': None, 'Status': 'no face'}]
        for i in range(len(result['Result'])):

            resultName = result['Result'][i][0]
            resultIsClean = result['Result'][i][1]

            # Check here to see if the staffID has been seen in the last 30 seconds (to mitigate
            # multiple alerts given out)
            # If the staffID has NOT been seen, add it to pqueue, if it has YES, then stop this task and continue
            if(resultName != None and self.staff_checker(resultName) == 0):
                # add the staffID and timestamp kv pair to list
                self.staffIDList[resultName] = time.time()
                self.logger.info("Added staff member to SEEN list")
            else:
                return

            # Check the status of the staff member. There will always be a welcome message sent here.
            # Once the welcome message is sent to the audio device, the payload will be placed in the msqueue to
            # be sent later to see if a further alert is needed.

            # Get data from MongoDB on that particular staff member
            collection = self.mongo.test.jhm
            staffDoc = collection.find_one({"Name": resultName})
            nodDoc = collection.find_one({"NodeID": self.NODE_ID })

             # Druid data schema : type, nodeID, staffID, staff_title, unit, room_number, response_type, response_message
            if(resultIsClean == False):
                self.send_druid_data("Entry", nodDoc["NodeID"], staffDoc["Name"], staffDoc["Title"], nodDoc["Unit"], nodDoc["RoomNumber"], "Entry", "Not clean")
                # self.send_druid_data("Entry", "DEMO1", resultName, "Nurse", "ICU", "TIFT1", "Entry", "Not clean")
                self.welcomequeue.put(resultName)
            elif(resultIsClean == True):
                self.send_druid_data("Entry", nodDoc["NodeID"], staffDoc["Name"], staffDoc["Title"], nodDoc["Unit"], nodDoc["RoomNumber"], "Entry", "Clean")
                # self.send_druid_data("Entry", "DEMO1", resultName, "Nurse", "ICU", "TIFT1", "Entry", "Clean")
                self.welcomequeue.put(resultName)
                return

            # Determine the hygiene status of the staff member, if there is a staff member face and they are not on dispenser list
            ##### MIGHT HAVE TO MAKE THIS A LOOP IF WE HAVE MORE THAN 1 PERSON IN PHOTO #####
            self.msgqueue.put(((timestamp + float(self.ALERT_TIME_DELAY)), resultName, headers))


    # Thread that will run in a loop that will constantly check in the pqueue for any payloads that need to be processed and sent to the server
    def control_thread(self): # always running on startup

        #Create new list and timestamp for payload
        images = []
        timestamp = None
        payload = None
        headers = None

        while(True):

            ## Continuously grab the images from the queue and send it to the server
            if(not self.pqueue.empty()):


                self.logger.info('Sending images to server')

                # Then loop through them all and put them in the image list
                while(not self.pqueue.empty()):
                    # Dequeue to get the first preprocessed image
                    tstamp, pload, hder = self.pqueue.get()

                    if(timestamp == None):
                        # Add the first image timestamp so that the rest of the images in this batch have the same timestamp
                        timestamp = tstamp
                        payload = pload
                        headers = hder

                    # Create an HTTP thread for just this request
                    # and send to HTTP thread
                    http_thread = threading.Thread(kwargs={'timestamp': timestamp, 'payload': payload, 'headers': headers}, target=client.http_thread)
                    http_thread.daemon = True
                    http_thread.start()

                    self.logger.info('HTTP Thread created for this request')

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

                # Create list of names that need to be alerted
                StaffList = []

                # Dequeue head and then keep dequeuing until head is 1 second later than earliest timestamp
                # Now that 30 sec have past, we need to check and see if they have actually washed their hands in that time-frame
                timestamp, staffname, headers = self.msgqueue.get()
                StaffList.append(staffname)

                self.logger.info("Sending check to see if they washed hands")

                # Send second post request again and check result (see if staff member has
                # used a hand hygiene device yet.)
                # If there is a face, and it is staff, and they are still not in the dispenser list, send an alert to them
                # payload = {'StaffList': staffname, 'Timestamp': timestamp}
                # namesToBeAlerted.append(staffname)


                # Keep dequing the alert queue as long as the timestamps are the same (means that they were found in the same picture)
                # and adding the names into the list
                while(self.peek_timestamp_at_alert() == timestamp):
                    t_timestamp, t_staffname, t_headers = self.msgqueue.get()
                    StaffList.append(t_staffname)

                payload = {'StaffList': StaffList, 'Timestamp': timestamp}

                result = None
                try:
                    result = requests.post(self.postEntryStaffCheck, json=payload, headers=headers)
                except requests.exceptions.Timeout:
                    self.logger.error("Timeout due to unreliable server connection - dropping image")
                    continue
                except:
                    self.logger.error("Tensorflow server unreachable, will save alert for later")
                    continue

                # When the server returns STATUS and NAME of staff member.
                # Send an alert accordingly.
                result = result.json()

                self.logger.info("Alert: " + str(result))

                # MongoDB
                collection = self.mongo.test.jhm

                # Returns [['name', 0/1], [name2, 0/1], ...]

                isAllStaffClean = True

                for i in range(len(result)):


                    resultName = result[i][0]

                    staffDoc = collection.find_one({"StaffID": resultName })
                    nodDoc = collection.find_one({"NodeID": self.NODE_ID })

                    # If one of these results are ever FALSE then that means we need to send out an alert because
                    # one of these staff members are NOT CLEAN
                    if result[i][1] == False:
                        isAllStaffClean = False

                        # Send Alert Given event to druid
                        self.send_druid_data("Alert", nodDoc["NodeID"], staffDoc["Name"], staffDoc["Title"], nodDoc["Unit"], nodDoc["RoomNumber"], "Alert", "Alert given")
                        continue
                    else:
                        # Staff member is clean, send event to druid, DO NOT give alert
                        self.send_druid_data("Alert", nodDoc["NodeID"], staffDoc["Name"], staffDoc["Title"], nodDoc["Unit"], nodDoc["RoomNumber"], "Alert", "No alert")



                if isAllStaffClean == False:
                    self.send_alert("reminder")
                else:
                    self.send_alert("clean")

                ## If we get "Status" = True message then that means that the staff member has breached protocol and not washed
                ## their hands within the 20 second period. If "Status" = False the staff member is clean and has used a soap dispenser within
                ## the alloted timeframe


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

        if(time.time() - self.staffIDList.get(staffID) > float(self.ALERT_TIME_DELAY)):
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
    logging.info('Created Control Thread')
    alert_thread = threading.Thread(name='alert_thread', target=client.alert_thread)
    logging.info('Created Alert Thread')
    control_thread.daemon = True
    alert_thread.daemon = True
    control_thread.start()
    alert_thread.start()
    logging.info('Control and Alert Threads Started')

    # sensor delay counter
    client.isSensorInDelayMode = False

    # Main loop for IoT Device
    while(True):


        if GPIO.input(4): # If the PIR sensor is giving a HIGH signal

            client.captureImage(client)

            # Sleep due to sensor delay time
            time.sleep(0.5)

            client.isSensorInDelayMode = True

        # UN-NEEDED FOR NEW PIR ##
        # Check if signal on low delay and take 3 more pictures
        # Yes I repeat code here - will make function for this later.
        elif GPIO.input(4) == 0 and client.isSensorInDelayMode == True:

            for x in range(3):

                    print("taking photo in delay mode")
                    client.captureImage(client)

                    # Take 1 photo every second for 3 seconds in delay mode
                    time.sleep(1)

            client.isSensorInDelayMode = False
