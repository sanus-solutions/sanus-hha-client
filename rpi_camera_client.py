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

"""
	Class to encapsulate the Raspberry Pi IoT device that will be attached to the doorways of hospital patient rooms. 
"""
class PiClient:
    
    def __init__(self):
        # TODO: set location in environment variable
        # get location/deviceID from envvar and init with client type
        #self.ctype = os.environ['CLIENT_TYPE']
        self.CTENTRY = "ENTRY"
        #self.node_id = os.environ['LOCATION']
        self.NODE_ID = "demo_entry" #this will change once we place a random gen here
        
        # GPIO pins initialization for PIR sensor
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(11, GPIO.IN)

        # Camera Init
        self.camera = picamera.PiCamera()
        self.camera.resolution = (640, 480)
        self.camera.start_preview(fullscreen=False, window=(100, 20, 0, 0))
        time.sleep(2)
        
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
        self.shape = '(480, 640, 3)'
        self.image = np.empty((480, 640, 3), dtype=np.uint8)
        
        # Server info
        SERVER_HOST = '192.168.0.106'
        SERVER_PORT = '5000'
        
        # API URL       THE SERVER HOST AND PORT WILL BE IN CONFIG FILE LATER
        self.url = 'http://' + SERVER_HOST + ':' + SERVER_PORT + '/sanushost/api/v1.0/entry_img'
        
        # Druid Server
        DRUID_SERVER_HOST = '192.168.0.105'
        DRUID_SERVER_PORT_DATA = '8200'
        DRUID_SERVER_PORT_QUERY = '8082'
        self.DRUID_SERVER_HEADERS = {'Content_Type': 'application/json'}

        # API url Druid       THE SERVER HOST AND PORT WILL BE IN CONFIG FILE LATER
        self.postData = 'http://' + DRUID_SERVER_HOST + ':' + DRUID_SERVER_PORT_DATA + '/v1/post/hospital'
        self.postQuery = 'http://' + DRUID_SERVER_HOST + ':' + DRUID_SERVER_PORT_QUERY + '/druid/v2?pretty'
        
          
        # Time delay for alert sent in seconds
        self.ALERT_TIME_DELAY = 20

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
            print(result.json())
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
        

    # Thread that will run in a loop that will constantly check in the pqueue for any payloads that need to be processed and sent to the server
    def control_thread(self): # always running on startup
        
        while(True):
            if(not self.pqueue.empty()):
                
                # Dqueue and post request to get face statistics 
                timestamp, payload, headers = self.pqueue.get()
                 
                # Send post request to http_thread for api call
                # send to HTTP thread
                http_thread = threading.Thread(kwargs={'timestamp': timestamp, 'payload': payload, 'headers': headers}, target=client.http_thread)
                http_thread.daemon = True
                http_thread.start()
                        

    # Thread that will constantly run on startup and only grab jobs from msgqueue that need to be sent
    # to the server to determine if a second alert needs to be sent to a staff member
    def alert_thread(self):
        while(True):
            
            # First check and see if we need to send welcome alerts to anyone into the room
            if(not self.welcomequeue.empty()):
                print("sending welcome message")
                self.send_welcome(self.welcomequeue.get())
            
            # check queue to see if it has passed ALERT_TIME_DELAY secs from current time
            if(self.peek_timestamp_at_alert() == -1):
                continue
            elif(self.peek_timestamp_at_alert() - time.time() <= 0.0):
                
                # Dequeue head and then keep dequeuing until head is 1 second later than earliest timestamp
                # Now that 30 sec have past, we need to check and see if they have actually washed their hands in that time-frame
                timestamp, payload, headers = self.msgqueue.get()
           
                # Send second post request again and check result.
                # If there is a face, and it is staff, and they are still not in the dispenser list, send an alert
                payload["Timestamp"] = time.time()
                result = requests.post(self.url, json=payload, headers=headers)

                # When the server returns STATUS and NAME of staff member.
                # Send an alert accordingly.
                
                print(result.json())
                
                
                ## If we get "Status" = True message then that means that the staff member has breached protocol and not washed
                ## their hands within the 20 second period. If "Status" = False the staff member is clean and has used a soap dispenser within
                ## the alloted timeframe
                
                if(result.json()['Status'] == True):
                    self.send_druid_data("alert", self.NODE_ID, result.json()['StaffID'], "Nurse", "ICU", "3500", "alert", "alert given")
                    self.send_alert(result.json()['StaffID'])
                elif(result.json()['Status'] == False):
                    self.send_druid_data("alert", self.NODE_ID, result.json()['StaffID'], "Nurse", "ICU", "3500", "alert", "no alert")
                    self.send_alert("clean")             
                    
    # thread for posting and waiting for HTTP response
    def http_thread(self, timestamp, payload, headers):
        
        # Send post request to the server
        result = requests.post(self.url, json=payload, headers=headers)
        
        print(result.json()['StaffID'])
        
        # Return from thread if no face
        if(result.json()['Status'] == 'no face' or result.json()['StaffID'] == None):
            return

        # Check here to see if the staffID has been seen in the last 30 seconds.
        # If not, add it to pqueue, if yes, stop this task and continue

        if(result.json()['StaffID'] != 'None' and self.staff_checker(result.json()['StaffID']) == 0):
            # add the staffID and timestamp kv pair to list
            self.staffIDList[result.json()['StaffID']] = time.time()
            print("adding staff name to list")
        else:
            return

        # Check the status of the staff member. There will always be a welcome message sent here.
        # Once the welcome message is sent to the audio device, the payload will be placed in the msqueue to
        # be sent later to see if a further alert is needed.

        # Druid data schema : type, nodeID, staffID, staff_title, unit, room_number, response_type, response_message
        if(result.json()['Status'] == True):
            self.send_druid_data("entry", self.NODE_ID, result.json()['StaffID'], "Nurse", "ICU", "3500", "entry", "not clean")
            self.welcomequeue.put(result.json()['StaffID'])
        elif(result.json()['Status'] == False):
            self.send_druid_data("entry", self.NODE_ID, result.json()['StaffID'], "Nurse", "ICU", "3500", "entry", "clean")
            self.welcomequeue.put(result.json()['StaffID'])
            return

        # Determine status of person, if there is a staff member face and they are not on dispenser list
        self.msgqueue.put(((timestamp + self.ALERT_TIME_DELAY), payload, headers))


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
            # if the time delay is not long enough, disregard this event, ther should be NO ALERT
            return 1
        
        
      
#### MAIN ####
if __name__ == '__main__':
    client = PiClient()
    
    # Start Major Threads
    control_thread = threading.Thread(name='control_thread', target=client.control_thread)
    alert_thread = threading.Thread(name='alert_thread', target=client.alert_thread)
    control_thread.daemon = True
    alert_thread.daemon = True
    control_thread.start()
    alert_thread.start()
    
    # sensor delay counter
    senseDelayPic = False

    # Main loop for IoT Device 
    while(True):
        
        if GPIO.input(11): # If the PIR sensor is giving a HIGH signal
            
            # Initial timestamp of image capture
            timestamp = time.time()
            
            # Take a picture, then send that picture to the HTTP thread
            img = np.empty((480, 640, 3), dtype=np.uint8)
            client.camera.capture(img, 'rgb')
          
            image_temp = img.astype(np.float64)
            image_64 = base64.b64encode(image_temp).decode('ascii')
            
            client.prepare_and_process(client.NODE_ID, timestamp, image_64, client.shape)
            
            # Sleep due to sensor delay time
            time.sleep(1)
            
            senseDelayPic = True
            
            
        # Check if signal on low delay and take 3 more pictures
        # Yes I repeat code here but I don't want to make a function for this.    
        elif GPIO.input(11) == 0 and senseDelayPic == True:
            
            for x in range(3):
                    
                    print("taking photo in delay mode")
                    
                    # Initial timestamp of image capture
                    timestamp = time.time()
                    
                    # Take a picture, then send that picture to the HTTP thread
                    img = np.empty((480, 640, 3), dtype=np.uint8)
                    client.camera.capture(img, 'rgb')
                  
                    image_temp = img.astype(np.float64)
                    image_64 = base64.b64encode(image_temp).decode('ascii')
                    
                    client.prepare_and_process(client.NODE_ID, timestamp, image_64, client.shape)
                    
                    # Sleep due to sensor delay time
                    time.sleep(1)
                    
            senseDelayPic = False
                
    
    


