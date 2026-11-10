# Installing Boom Box

No programming knowledge needed. Plan on about 30 minutes and an internet connection for the first install.

**You'll need:** a Mac or Windows PC with a headphone jack (or a USB audio adapter), the USB camera, the USB microphone, and the amplifier/speaker.

The Mac instructions come first. **Using a Windows PC? Go to [Installing on Windows](#installing-on-windows).**

---

## Quick install

For a Mac that already has Anaconda and the BoomBox folder:

1. Double-click **`Boom_Box_Setup.command`** (creates the `boombox` Anaconda environment, a few minutes).
   - If macOS blocks it, right-click > Open. If it asks for an administrator password, use the **[No password method](#no-password-method)** instead.
2. Double-click **`Boom_Box.command`** to start the program.
3. The first time, macOS asks for **Camera** and **Microphone** access for Terminal. Allow both, then
   quit and restart the program. (System Settings > Privacy & Security > Camera / Microphone.)

From a terminal instead: `conda activate boombox && python -m boombox`.

Starting from scratch? Follow the full steps below.

---

## Step 1. Check which kind of Mac you have
- Click the Apple menu () in the top-left corner, then **About This Mac**.
- If it says **Chip: Apple M1/M2/M3/M4…**, you have an **Apple Silicon** Mac.
- If it says **Processor: Intel…**, you have an **Intel** Mac.
- You'll need this in Step 2.

## Step 2. Install Anaconda (skip if it's already installed)
- Go to https://www.anaconda.com/download and download the **Mac** installer that matches your Mac from Step 1.
- Open the downloaded file and click through the installer, keeping all the default choices.
- **Not sure if it's already installed?** Open the **Terminal** app (press ⌘ + Space, type *Terminal*, press Return), type `conda --version` and press Return. If you see a version number, it's installed. If you see "command not found", install it.

## Step 3. Download the Boom Box program
- Go to https://github.com/vtbrak/BoomBox.
  - If the page says "404" or "not found", ask the lab member who owns the program to give your GitHub account access.
- Click the green **Code** button, then **Download ZIP**.
- Open your **Downloads** folder and double-click the ZIP file to unzip it. You'll get a folder named **BoomBox-main** (or **BoomBox-1.3** if you downloaded version 1.3).
- Move that folder to your **Desktop** and rename it **BoomBox**.

## Step 4. Run the one-time setup
- Open the **BoomBox** folder and **right-click** (or Control-click) **Boom_Box_Setup.command**, then choose **Open**.
  - The first time, macOS warns that the file is "from an unidentified developer". Click **Open**.
  - If there's no Open button, go to **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to the file's name, and try again.
  - **Asked for an administrator password?** Use the **[No password method](#no-password-method)** at the end of this guide instead.
- A Terminal window opens and downloads everything the program needs. This takes 5–15 minutes.
- When it says **"Done. Press Return to close."**, press Return.

## Step 5. Plug in the equipment
- **Camera:** into a USB port.
- **Microphone:** into a USB port.
- **Amplifier:** a cable from the Mac's **headphone jack** to the amplifier input. Keep the amplifier's volume low for now.

## Step 6. Start the program
- In the **BoomBox** folder, double-click **Boom_Box.command**.
  - If macOS blocks it, right-click → **Open**, as in Step 4.
- A Terminal window opens, followed by the Boom Box window.
- **Keep the Terminal window open.** Closing it quits the program.

## Step 7. Allow camera and microphone access
- The first time, macOS asks whether **Terminal** may use the **camera** and the **microphone**. Click **Allow** both times.
- Then **quit the program and start it again** (Step 6) so the permissions take effect.
- **No video, and no prompt appeared?** Go to **System Settings → Privacy & Security → Camera** and turn on **Terminal**. Do the same under **Microphone**. Then restart the program.

## Step 8. Set up the program (first time only)
- **Settings tab**
  - **Sound output:** choose **External Headphones**.
  - **Microphone:** choose your USB microphone. Click **Test mic** to check that it hears sound.
  - Click **Save settings and restart audio**.
- **Camera tab**
  - Choose your USB camera, keep **B 1280x720** and **30** fps, then click **Apply / restart camera**.
  - Adjust exposure, gain and focus while watching the video, then tick **Lock camera settings**.
- **Calibration tab:** once you have a sound level meter, follow the instructions at the top of that tab.
- **Session tab:** open the **Experimenter** list, choose **Add a name**, and type your name.

## Step 9. Make it easy to start next time (optional)
- Drag **Boom_Box.command** onto the right-hand side of the **Dock** (next to the Trash) so you can start the program with one click.

---

## Troubleshooting

| Problem | What to do |
|---|---|
| **"Could not find Anaconda"** | Anaconda isn't installed, or was installed somewhere unusual. Repeat Step 2, keeping the default choices. |
| **Setup mentions "Terms of Service"** | Open Terminal and run `conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main` and then `conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r`. Then repeat Step 4. |
| **"Permission denied" when opening a .command file** | Open Terminal and run `chmod +x ~/Desktop/BoomBox/*.command`. Then try again. |
| **Video window stays black** | See Step 7. Also unplug the camera, plug it back in, and click **Apply / restart camera**. |
| **No sound from the speaker** | Check that **Sound output** is **External Headphones** (Settings tab), the Mac isn't muted, and the amplifier is on. |
| **The camera isn't in the list** | Plug it in, then click **Refresh list** on the Camera tab. |

## Installing a newer version later
- Download and unzip the new version as in Step 3.
- **Before deleting the old BoomBox folder,** copy two folders from it into the new one:
  - **config**: your calibration, camera settings and experimenter names.
  - **Data**: your recorded sessions (unless you save them somewhere else).
- Run **Boom_Box_Setup.command** again (Step 4) in case anything the program needs has changed.

---

## No password method

Use this if double-clicking a `.command` file asks for an **administrator password** (common on macOS 15 Sequoia for downloaded files). Starting the files from Terminal with `bash` avoids that check, so no password is needed.

### 1. Install Anaconda
- Same as **Step 2** above. If it's already installed, skip this step.

### 2. Get the program folder
- Same as **Step 3** above: download the ZIP, unzip it, and put the **BoomBox** folder on your Desktop.

### 3. Open Terminal
- Press ⌘ + Space, type **Terminal**, and press Return.

### 4. Run the installer
- Type `bash` followed by **one space**. Don't press Return yet.
- Open the **BoomBox** folder in Finder and **drag `Boom_Box_Setup.command` into the Terminal window**. Its location appears after `bash `, for example:
  ```
  bash /Users/yourname/Desktop/BoomBox/Boom_Box_Setup.command
  ```
- Press **Return**.

### 5. Wait for "Done"
- Setup takes 5–15 minutes. When it says **"Done. Press Return to close."**, press Return.

### 6. Open the program the same way
- Type `bash` and **one space**, drag **`Boom_Box.command`** into the Terminal window, and press **Return**.
- Keep the Terminal window open while you use the program. Then continue with **Steps 7 and 8** above (camera/microphone permission and first-time settings).

### Every time after that
Use these steps whenever you start the program again, including after closing it, logging out, or restarting the Mac. **You don't need to open Anaconda or run the installer again**; `Boom_Box.command` switches on everything it needs by itself.

1. **Plug in the equipment first**: camera, USB microphone, and the amplifier cable in the headphone jack.
2. **Open Terminal.**
3. **Type `bash` and one space, drag in `Boom_Box.command`, and press Return.**

**Important**
- The **space after `bash`** is required before you drag the file in.
- Drag the **file** (`Boom_Box.command`), not the BoomBox folder.
- **Leave the Terminal window open** while you use the program. Closing it quits the program.
- Close the program with the red button on its own window. Your settings, calibration and experimenter names are kept.
- Run the installer (`Boom_Box_Setup.command`) again only after installing a newer version of the program.

### If something goes wrong
- **"No such file or directory":** the space after `bash` was missing, or the file was moved. Try again, dragging the file from the BoomBox folder.
- **"is a directory":** you dragged the BoomBox folder instead of the file inside it.

### Optional: make double-clicking work without a password
- In Terminal, type `xattr -dr com.apple.quarantine` and **one space**, drag the **BoomBox folder** into the window, and press Return.
- This removes macOS's "downloaded from the internet" flag from the program's files, so double-clicking them works normally. It only changes files you own, so no password is needed.

---

## Installing on Windows

Windows support is new in this version and has not yet been tested on a PC. Please note anything that doesn't match these steps.

### Step 1. Install Anaconda (skip if it's already installed)
- Go to https://www.anaconda.com/download and download the **Windows** installer.
- Run it and keep the default choices, including **"Just Me"**. That choice doesn't need an administrator password.

### Step 2. Download the Boom Box program
- Go to https://github.com/vtbrak/BoomBox, click the green **Code** button, then **Download ZIP**.
- In your **Downloads** folder, right-click the ZIP file and choose **Extract All…**, then **Extract**.
- Move the extracted folder (**BoomBox-main**) to your **Desktop** and rename it **BoomBox**.

### Step 3. Run the one-time setup
- Open the **BoomBox** folder and double-click **Boom_Box_Setup.bat**.
  - If Windows shows **"Windows protected your PC"**, click **More info**, then **Run anyway**. This doesn't need an administrator password.
  - The file may show as just **Boom_Box_Setup** if Windows hides file extensions. It's the one whose type is "Windows Batch File".
- A black window opens and downloads everything the program needs (5–15 minutes).
- When it says **"Done."**, press any key to close it.

### Step 4. Plug in the equipment
- **Camera** and **microphone:** into USB ports.
- **Amplifier:** a cable from the PC's **headphone jack** (or a USB audio adapter) to the amplifier input. Keep the amplifier's volume low for now.

### Step 5. Start the program
- Double-click **Boom_Box.bat**. If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**.
- A black window opens, followed by the Boom Box window.
- **Keep the black window open.** Closing it quits the program.

### Step 6. Allow camera and microphone access
- If the video stays black, or the microphone hears nothing, open **Settings → Privacy & security → Camera** and turn on **Let desktop apps access your camera**.
- Do the same under **Settings → Privacy & security → Microphone**.
- Then close and restart Boom Box.

### Step 7. Set up the program (first time only)
- **Settings tab**
  - **Sound output:** choose the headphone or speaker output that goes to the amplifier, preferably one ending in **[Windows WASAPI]**, which has the most accurate timing.
  - **Microphone:** choose the USB microphone, preferably one ending in **[Windows WASAPI]**. Click **Test mic** to check it.
  - Click **Save settings and restart audio**.
- **Camera tab**
  - Choose your USB camera, keep **B 1280x720** and **30** fps, then click **Apply / restart camera**.
  - Click **Open camera settings window**. Turn off automatic exposure, then set exposure, gain and focus while watching the preview.
  - Close that window and tick **Lock camera settings**. The values are saved and re-applied every session.
- **Calibration tab:** as on the Mac. Afterwards, leave the **Windows volume** at the same level for every session.
- **Session tab:** open the **Experimenter** list, choose **Add a name**, and type your name.

### Starting the program each time on Windows
- Plug in the equipment, then double-click **Boom_Box.bat**. You don't need to open Anaconda or rerun the setup.
- Keep the black window open while the program runs.
- Optional: right-click **Boom_Box.bat** → **Show more options** → **Send to** → **Desktop (create shortcut)**.

### Windows troubleshooting

| Problem | What to do |
|---|---|
| **"Could not find Anaconda"** | Repeat Step 1, keeping the default choices. |
| **Camera not sending video** | Close other programs that might be using the camera (Camera app, Zoom, Teams), check Step 6, then click **Apply / restart camera**. |
| **The camera isn't in the list** | Plug it in, then click **Refresh list** on the Camera tab. |
| **No sound from the speaker** | Choose a different **Sound output** on the Settings tab (try the [Windows WASAPI] one for your headphone jack), check the Windows volume isn't muted, and that the amplifier is on. |
| **Notifications make sounds during sessions** | Turn on **Do not disturb** in **Settings → System → Notifications**. |
