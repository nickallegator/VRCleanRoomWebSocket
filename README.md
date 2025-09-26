# Setup and Operational Instructions

## Prerequisite: Installing Anaconda:

Download and install Anaconda Python: https://www.anaconda.com/download

## Setting Up Code and Python Environment:

Clone the Github Repo VRCleanRoomWebSocket
Using Anaconda Powershell, CD into cloned Github directory
Run the command: ‘conda env create -f environment.yml’ to create the Python environment.
Run the command: ‘conda activate UnityWebSocket’ to activate the environment created previously.


## Running the WebSocket:

Ensure your Conda environment is created and activated.
If on campus, ensure both the computer running the Python environment and the Meta Quest device are connected to Tiger Wifi Guest.
Run the command: ‘python launch_websocket.py’’
Keep the powershell window open. Closing it will close the web socket.
To close the websocket, type ‘ control c’

## Connecting to WebSocket from HMD:

Continue through the enter name page.
When reaching the enter WebSocket page, check the output of the launch_websocket powershell window.
You should see two provided websocket addresses, one is used for connecting to a web socket hosted on the same device as the HMD (If you are running from Unity) and one for connecting to the web socket from a different device (When running the standalone apk on the HMD)
Enter the correct websocket address on the VR menu using the virtual keyboard. NOTE: you need to use two hands to hold the shift key for the ‘:’ characters.
When the headset is successfully connected it will go to the module selection page. If it has not successfully connected, it will give an error message and not advance.

## Addition Notes:
If you want to save CSV files locally to the headset toggle the functioning on (the button should be green).
If you want to run the NewVRCleanRoom without Websocket logging click the Bypass Websocket button. NOTE: If you enable saving locally this setting persists when bypassing the web socket connection.
