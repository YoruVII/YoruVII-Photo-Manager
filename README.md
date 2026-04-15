![Project Logo]("Readme%20Assets/YoruVII%20Image%20Manager.png")
# YoruVII-Photo-Manager 
YoruVII Photo Manager (YPM) is a VRChat photo uploading tool built to be:
1. Lightweight as I could get python to be at idle it only uses 38.4 MB of memory when it is uploading photos it uses a little bit of CPU but it is low priority so it stays out of the way if you really need that .2% of your CPU
2. Fast it is snappy as can be as soon as VRC is done writing the file its sent (+ the delay if you set that)
3. **NO LOGGINS** it uses the information that is already on the photo to get the photographer's username and time the photo was taken. If you use VRCX's screenshot helper (I would highly recommend it) you also get the world, world link, and other users in the instance.
4. Customizable pictures path, message text, and the Webhook URL

The intention is to set this to run at startup and then you can just forget about it if you set up your webhook it will just open in the tray and use 38.4mb of ram at low priority so on modern systems 0.24% of your ram
The startup file is ```%AppData%\Microsoft\Windows\Start Menu\Programs\Startup\``` just make a shortcut to the exe and put it here

# Installation:
Download the exe (I would recommend putting it in an empty folder because it will create a settings file) and launch it set the discord webhook click save and hide to try and you are done
If you want [VRCX](https://github.com/vrcx-team/VRCX) integration just make sure to turn on screenshot helper that is Settings>Pictures at the top Enable Screenshot helper and any other options you want



# Disclaimer
I have never coded before and have no clue what I am doing so make fun of my code and help me fix it if you see any issues if you find any bugs you can DM me at YoruVII on discord or make a issue. a LLM helped me alot to write this code so im sure some of it is stupid or not nessisary. This is also a new program as of 4/15/2026 so it probably has bugs as I have not used it for long. (I suspect I need to account for prints and stickers and stuff but im poor and do not have VRC+ so ill find that issue in a public some time)

This program also has no updater so the version you download is the version you use if you want to update just replace the exe with the new one
