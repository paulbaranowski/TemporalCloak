# TemporalCloak
Time-Based Steganography

## Install
```
cd <project_name>
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
## Usage

### Demo 1
The client asks what message you want to send, 
then generates random data and sends it to the server
one byte at a time.
Once it gets to the end of the message, it will loop 
and send it again forever. The message is encoded in the
time differences between bytes.

Start the server with:
```
python demo1_server.py
```
Then run the client:
```
python demo1_client.py
```


### Demo 2
In Demo 2, the transmission is reversed: the server sends
a message to the client. The server is a web server that 
serves up images if you access it from a web browser. If you
access it with the demo client however, you will receive a 
secret message. The message in this case is a random quote. 
The message is encoded between chunks of data (instead of single
bytes like in Demo 1). The message is only sent once. 
The web server is based on Tornado.

Start up the server:
```
python demo2_server_tornado.py
```
Now you can go to http://localhost:8888 and see an image.

Now run the client:
```
python demo2_client_tornado.py
```

## Testing
```
python test.py
```

## Acknowledgements
Quotes are from:
https://github.com/JamesFT/Database-Quotes-JSON
Images are from:
https://www.pexels.com/
