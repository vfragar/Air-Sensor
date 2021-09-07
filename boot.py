# ---------------------------------------- 
# ----------  LIBRARIES REGION  ---------- 
# ---------------------------------------- 


# General libraries
import pycom
import machine
from machine import I2C
from machine import Pin
import pycom
import time
import socket
import json
import ujson
import ubinascii
import network
from network import WLAN
from network import LoRa
import binascii
import struct
import config
import os
from microWebSrv import MicroWebSrv
from crypto import AES
import crypto

# Custom sensor libraries: bme280, max 31865 chipsets and Temperature details
import bme280
from lopy_max31865 import MAX31865
from temperature import Temperature


# ---------------------------------------- 
# ------------- CODE REGION  ------------- 
# ---------------------------------------- 


# ----------  Global variables REGION  ---------- 

# Initializing i2c port communication for getting the univocal ID from an electronic chipset
i2c = I2C(0, I2C.MASTER, baudrate=100000, pins=('P8','P9'))
sensor_ref_raw = i2c.readfrom_mem(80, 0, 9)
_ref = ubinascii.hexlify(sensor_ref_raw)

sensor_reference = str(bytearray(_ref), 'UTF-8')
sensor_reference = sensor_reference[2:14]

key = b'ujso3kgnxtuth2bs' # 128 bit (16 bytes) key
iv = crypto.getrandbits(128) # hardware generated random IV 

# Initializing sensors comunication
try:
    bme = bme280.BME280(i2c=i2c)
    rtd = MAX31865()
    tmp = Temperature()
    print("Sensors ready.")
except:
    print("Error on i2c bus. Unable to read BME280 data")


# ----------  POST/GET SAVE REGION	  ----------
# loading settings from an encrypted file in flash memory

def LoadGlobalSettings():
    try:
		print("Trying to load GLOBAL...")
		f = open('/flash/globalsettings.bin', 'r') # open for reading
		encrypted_data_line = f.read()
		f.close()
		encrypted_data = encrypted_data_line.encode(hex)
		cipher = AES(key, AES.MODE_CFB, encrypted_data[:16]) # on the decryption side
		raw = cipher.decrypt(encrypted_data[16:])
		original = raw.decode("utf-8")
		print("LoadGlobalSettings: ")
		print(original)
		time.sleep(1)
		return original
    except:
        print("Error or file not found")

# ----------  POST/GET SAVE REGION	  ---------- 
# saving settings from website to an encrypted file in flash memory

def SaveGlobalSettings(settings):
	dec_set = settings.decode('utf-8')
	# example: '{"gbl_user_code":"rv50V9gDybyE5oMr", "wifi_enabled":"1", "lora_enabled":"0", "wifi_ssid":"WLAN_XXX", "wifi_password":"123456*", "wifi_ip":"", "wifi_mask":"", "wifi_gateway":"", "wifi_dns":"", "lorafreq":"868100000", "loragwdr":"SF7BW125", "loranodedr":"5", "mqtt_uri":"www.example.com", "mqtt_user":"", "mqtt_password":"", "mqtt_topic":"home/inputs/air"}'
	cipher = AES(key, AES.MODE_CFB, iv)
	encrypted_data = iv + cipher.encrypt(dec_set)
	try:
		open('/flash/globalsettings.bin', 'w').close()
		time.sleep(1)
	except:
		print("Error erasing globalsettings file")
	f = open('/flash/globalsettings.bin', 'w') # open for writing
	f.write(encrypted_data)
	f.close()
	print("GLOBAL Settings saved successfully")

# ----------  HTTP HANDLERS  ---------- 
	
def HttpHandlerDHTGet(httpClient, httpResponse):
    try:
        t, h = 23.3, 66.6
        if all(isinstance(i, float) for i in [t, h]):   # Confirm values
            data = '{0:.1f}&deg;C {1:.1f}%'.format(t, h)
        else:
            data = 'Invalid reading.'
    except:
        data = 'Attempting to read sensor...'
        
    httpResponse.WriteResponseOk(
        headers = ({'Cache-Control': 'no-cache'}),
        contentType = 'text/event-stream',
        contentCharset = 'UTF-8',
        content = 'data: {0}\n\n'.format(data) )

def HttpHandlerDashboardGet(httpClient, httpResponse):
    try:
        DryT = float(bme.temperature)
        HR = float(bme.humidity)
        Pressure = float(bme.pressure)
        data = '{ "t":'  + str(DryT) + ', "hr":'+ str(HR) + ',"p":' + str(Pressure) + ', "sr":450}'
        print(data)
    except:
        data = 'Attempting to read sensor...'

    httpResponse.WriteResponseOk(
        headers = ({'Cache-Control': 'no-cache'}),
        contentType = 'text/event-stream',
        contentCharset = 'UTF-8',
        content = 'data: {0}\n\n'.format(data) )
		
def HttpHandlerWBGTGet(httpClient, httpResponse):
	try:
		GlobeT = rtd.read()
		DryT = float(bme.temperature)
		HR = float(bme.humidity)
		Pressure = float(bme.pressure)
		Dewpoint = tmp.temp_dewpoint(DryT, HR)
		Wetbulb = tmp.temp_wetbulb(DryT, HR, Pressure)
		WBGT = tmp.temp_WBGT(GlobeT, Wetbulb, DryT)
		data = '{ "t":'  + str(DryT) + ', "hr":' + str(HR) + ',"p":' + str(Pressure) + ', "GlobeT":' + str(GlobeT) + ', "sr":450, "WBGT":' + str(WBGT) + ', "Dewpoint":' + str(Dewpoint) + '}'
		print(data)
	except Exception as e:
		data = str(e)

	httpResponse.WriteResponseOk(
		headers = ({'Cache-Control': 'no-cache'}),
		contentType = 'text/event-stream',
		contentCharset = 'UTF-8',
		content = 'data: {0}\n\n'.format(data) )

def HttpHandlerLEDPost(httpClient, httpResponse):
    content = httpClient.ReadRequestContent()
    colors = json.loads(content)
    print("colors", colors)

def HttpHandlerGlobalSettingsPost(httpClient, httpResponse):
    content = httpClient.ReadRequestContent()
    globalsettings = json.loads(content)
    SaveGlobalSettings(content)

# ----------  COMMUNICATION MODES  ----------  

# you can either choose to set the sensor as wifi device or a wifi ap
# wifi device to work as a normal electronic device connected to a wifi access point
# or wifi access point to generate a wifi access point with a self hosted dashboard to configurate everything in the sensor itself

def CommunicationMode():
    try:
        wlan = WLAN(mode=WLAN.STA)                              # setting up wlan communication
        button = Pin('P10', mode=Pin.IN, pull=Pin.PULL_UP)      # setting up pushbutton
        global_st = json.loads(LoadGlobalSettings())
        
        websrv = False
        if not button():                                        # pushbottom pushed
            print("Setting WLAN as an access point...")
            AP_PASSWORD = '123456abcdef'                        # access point password 
            AP_wlan = WLAN(mode=WLAN.AP, ssid='VF sensors ' + str(sensor_reference), auth = (WLAN.WPA2, AP_PASSWORD), antenna = WLAN.INT_ANT)   # access point SSID, password, antenna type
            AP_wlan.ifconfig(id = 1, config = ('10.0.0.10', '255.255.255.0', '0.0.0.0', '0.0.0.0'))                                             # webserver configuration
            routeHandlers = [ ( "/dht", "GET",  HttpHandlerDHTGet ), ( "/dashboard", "GET",  HttpHandlerDashboardGet ), ( "/wbgt", "GET",  HttpHandlerWBGTGet ),( "/led", "POST",  HttpHandlerLEDPost ),( "/globalsettings", "POST",  HttpHandlerGlobalSettingsPost )  ]    # webserver handlers
            srv = MicroWebSrv(routeHandlers=routeHandlers, webPath='/flash/www/')   # webserver setting up and website container folder
            srv.Start(threaded=True)                                                # initialize webserver
            websrv = False
            print("Done.")
        else:                                                   #pushbottom not pushed
            if (int(global_st['wifi_enabled']) == 1):
                wlan = WLAN(mode=WLAN.STA)
                wlan.connect(global_st['wifi_ssid'], auth=(WLAN.WPA, global_st['wifi_password']), timeout=5000)
                websrv = True
            if (int(global_st['wifi_enabled']) == 0):
                print("Wifi desconectada")
        
        if websrv:
            print("Trying to connect to", global_st['wifi_ssid'])
            while not wlan.isconnected():  
                machine.idle() 
            print("Connected to", global_st['wifi_ssid'])
    except:
        print("Error on network config")


# ----------  MAIN  ----------  
def main():
    CommunicationMode()


if __name__ == '__main__':
    main()
