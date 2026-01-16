import pygame
from pygame.locals import *
import requests
import argparse
from threading import Thread, Lock
from animatable import Animatable, TargetXLocation
import sys
import os
import io
from xml.etree import ElementTree

# Bluscreen is a 10-foot interface that displays the 'Now Playing' information
# for a BluOS player from Bluesound. This also allows some limited navigation
# (skip fwd) and volume control via the keyboard. See README.txt for more
# details.

# The port that Bluesound uses for its control API
BLUPORT = 11000

class NowPlaying:
    # This minimalist 'Now Playing' display has 3 elements that are animated:
    #   - an album image
    #   - a line1 string
    #   - a line2 string
    # Each has a current and previous value
    # There is also a static 'service' graphic that shows the current
    # music serivce, this is displayed in the bottom right corner.

    # Reset the current info parameters
    def resetCurrent(self):
        self.currImageBytes = None
        self.imageUrl = None
        self.serviceUrl = None
        self.serviceSurface = None
        self.currLine1 = None
        self.currLine2 = None

    # Reset the previous info parameters
    def resetPrev(self):
        self.prevImageBytes = None
        self.prevLine1 = None
        self.prevLine2 = None

    # Set up defaults and calculate font size
    def __init__(self, addr, port, screen, fontName):
        # basic params - IP address, port and screen instance
        self.ipaddr = addr
        self.port = port
        self.pygameScreen = screen

        # We keep a dict of animatable objects that we need to update
        self.animObjects = {}

        # init our current and previous data
        self.resetCurrent()
        self.resetPrev()

        # Mutex for swapping current/previous data
        self.mutex = Lock()

        # grab our working screen size
        self.screenW, self.screenH = self.pygameScreen.get_size()

        # The two lines of track info should take up about 40% of the screen,
        # do some calculations to convert pixels to points. A standard
        # conversion is that a 12-point font is about 16 pixels tall.
        text_area_height = int(self.screenH * 0.4)

        # allow enough space for 4 lines, even though we're using two so
        # we allow for padding above and below the text.
        self.textHeight = text_area_height // 4

        # now do our pixels to points conversion
        self.fontSize = int(self.textHeight / 1.3333)

        # Finally, allocate the appropriately sized font
        self.myFont = pygame.font.SysFont(fontName, self.fontSize)

    # Skip ahead to the next track
    def skip(self):
        try:
            response = requests.get(f"http://{self.ipaddr}:{self.port}/Skip")
            if response.status_code != 200:
                print(f"Bad return status: {response.status_code}")
                sys.exit(1)
        except requests.exceptions.ConnectTimeout:
            pass

        # No updates here, the next updateTrack will pick up the change.
        return

    # Toggle play/pause
    def togglePause(self):
        try:
            response = requests.get(f"http://{self.ipaddr}:{self.port}/Pause?toggle=1")
            if response.status_code != 200:
                print(f"Bad return status: {response.status_code}")
                sys.exit(1)
        except requests.exceptions.ConnectTimeout:
            pass

        return

    # Volume up
    def volUp(self):
        try:
            response = requests.get(f"http://{self.ipaddr}:{self.port}/Volume?db=2")
            if response.status_code != 200:
                print(f"Bad return status: {response.status_code}")
                sys.exit(1)
        except requests.exceptions.ConnectTimeout:
            pass

        return

    # Volume up
    def volDown(self):
        try:
            response = requests.get(f"http://{self.ipaddr}:{self.port}/Volume?db=-2")
            if response.status_code != 200:
                print(f"Bad return status: {response.status_code}")
                sys.exit(1)
        except requests.exceptions.ConnectTimeout:
            pass

        return

    # Do the necessary URL translation to fetch the specified image URL bytes.
    # An img URL can be relative to the Bluesound API or a standalone URL
    def fetchImgContents(self, imgUrl):
        # Sometimes the image info is a relative URL based on the Bluesound player's
        # http address, and other times it is a standalone URL that references some
        # other site.
        url = f"http://{self.ipaddr}:{self.port}/{imgUrl}"
        # If the image URL starts with http: or https: then it is standalone
        if imgUrl.startswith('https:') or imgUrl.startswith('http:'):
            url = imgUrl
        response = requests.get(url)
        if response.status_code == 200:
            return response.content
        else:
            return None

    # Utility method to query the current player status and fetch any album art
    # and service icons
    def queryStatus(self):
        # These are the fields that we're looking for in the returned XML
        # (plus some derived fields)
        info = { 'album': None, 'artist': None, 'image': None, 'name': None,
             'twoline_title1': None, 'twoline_title2': None, 'serviceName': None,
             'serviceIcon': None, 'streamFormat': None, 'currentImageBytes': None,
             'currentServiceBytes': None }

        # get the player 'Status'
        try:
            response = requests.get(f"http://{self.ipaddr}:{self.port}/Status", timeout=2)
            if response.status_code != 200:
                info['twoline_title1'] = f'Bad status response code: {response.status_code}'
                return info
        except requests.exceptions.ConnectTimeout:
            info['twoline_title1'] = 'Timeout connecting to player'
            return info

        # If we get here, then the request was successful. Parse the XML from the Bluesound
        # player's response
        tree = ElementTree.fromstring(response.content)

        # Copy any fields that we want from the XML into the above dict
        for child in tree:
            if child.tag in info:
                info[child.tag] = child.text

        return info

    # Take an image surface and rescale it to be a specified height
    def scaleImageForHeight(self, imgSurface, newHeight):
        p_width, p_height = imgSurface.get_size()
        ratio = newHeight / p_height
        newWidth = int(p_width * ratio)
        return pygame.transform.smoothscale(imgSurface, (newWidth, newHeight))

    # do the query to the Bluesound player and track any changes since
    # the last query. This runs in a separate thread and uses a mutex when
    # updating the instance variables.
    def updateTrack(self):
        # Track what we need to swap in our critical region
        imageChanged = False
        line1Changed = False
        line2Changed = False

        # New surfaces/values
        newImageSurface = None
        newImageBytes = None
        newLine1Surface = None
        newLine1Value = None
        newLine2Surface = None
        newLine2Value = None
        newServiceSurface = None

        # Defaults for animation
        # Speed for new items to scroll in from the right hand side
        newSpeed = 5
        # Speed for 'killed' items to scroll from the center to off the left hand side
        killSpeed = 12

        # Our line 1 and line 2 Y values
        line1Y = self.screenH - (self.textHeight * 3)
        line2Y = self.screenH - (self.textHeight * 2)

        # Query the player status
        info = self.queryStatus()

        # See if the image has updated, if it has then we create
        # a new pygame surface for it.
        if info['image'] != self.imageUrl:
            imageChanged = True
            info['currentImageBytes'] = self.fetchImgContents(info['image'])
            if info['currentImageBytes'] != None:
                image_file_like = io.BytesIO(info['currentImageBytes'])
                try:
                    # image sizes vary, scale this one to fit our image area on the display
                    imageHeight = int(self.screenH * 0.6) - 100

                    newImageSurface = pygame.image.load(image_file_like)
                    newImageBytes = info['currentImageBytes']
                    newImageSurface = self.scaleImageForHeight(newImageSurface, imageHeight)
                except Exception as e:
                    # Give up, don't display an image
                    newImageSurface = None

        # currentServiceBytes should be an icon that shows the current music service
        # (like Amazon, Qobuz, Tidal, etc.)
        if info['serviceIcon'] != self.serviceUrl:
            if info['serviceIcon'] != None:
                try:
                    info['currentServiceBytes'] = self.fetchImgContents(info['serviceIcon'])
                    # Treat the bytes like a file
                    image_file_like = io.BytesIO(info['currentServiceBytes'])
                    newServiceSurface = pygame.image.load(image_file_like)
                    # image sizes vary, scale this one to fit our image area on the display
                    imageHeight = self.fontSize
                    newServiceSurface = self.scaleImageForHeight(newServiceSurface, self.fontSize)
                    self.serviceUrl = info['serviceIcon']
                except Exception as e:
                    # Give up, don't display a service image
                    newServiceSurface = None
            else:
                newServiceSurface = None
        else:
            newServiceSurface = self.serviceSurface

        # Check the first text line to see if it has changed.
        if info['twoline_title1'] != None and info['twoline_title1'] != self.currLine1:
            line1Changed = True
            newLine1Value = info['twoline_title1']
            newLine1Surface = self.myFont.render(newLine1Value, False, (255, 255, 255))

        # Check the second text line to see if it has changed.
        if info['twoline_title2'] != None:
            if info['twoline_title2'] != self.currLine2:
                line2Changed = True
                newLine2Value = info['twoline_title2']
                newLine2Surface = self.myFont.render(newLine2Value, False, (255, 255, 255))
        else:
            # Special case - if nothing is playing, title2 is null.
            newLine1Value = 'Play queue is empty'
            if self.currLine1 != newLine1Value:
                line1Changed = True
                line2Changed = True
                imageChanged = True
                newLine1Surface = self.myFont.render(newLine1Value, False, (255, 255, 255))
                newImageSurface = None
                newLine2Surface = None
                newLine2Value = None

        # We're running in a thread here, so we use a mutex when we swap the current
        # and previous values so we don't change them partway though a display refresh
        with self.mutex:
            if imageChanged:
                # if we have a current image, kill it
                if 'currImage' in self.animObjects:
                    self.animObjects['prevImage'] = self.animObjects['currImage']
                    self.animObjects['prevImage'].kill()
                    self.animObjects['prevImage'].set_speed(killSpeed)
                    del self.animObjects['currImage']

                # if we have a new image, create an animatable to handle it - new images
                # start off the screen to the right then animate to the center
                if newImageSurface != None:
                    # create a new animatable for this image, stop when img is centered
                    newImageAnim = Animatable(newImageSurface, self.screenW + 100,
                                              TargetXLocation.CENTERED, 50, newSpeed, loop=False)
                    self.animObjects['currImage'] = newImageAnim
                # keep a copy of our current image url and bytes so we can track when the image
                # changes
                self.currImageBytes = newImageBytes
                self.imageUrl = info['image']

            if line1Changed:
                if 'currLine1' in self.animObjects:
                    self.animObjects['prevLine1'] = self.animObjects['currLine1']
                    self.animObjects['prevLine1'].kill()
                    self.animObjects['prevLine1'].set_speed(killSpeed)
                    del self.animObjects['currLine1']

                if newLine1Value != None:
                    w, h = newLine1Surface.get_size()
                    loop = (w > self.screenW)

                    # create a new animatable for this image
                    newLine1Anim = Animatable(newLine1Surface, self.screenW + 150,
                                              TargetXLocation.CENTERED, line1Y, newSpeed, loop=loop)
                    self.animObjects['currLine1'] = newLine1Anim

                self.currLine1 = newLine1Value

            if line2Changed:
                if 'currLine2' in self.animObjects:
                    self.animObjects['prevLine2'] = self.animObjects['currLine2']
                    self.animObjects['prevLine2'].kill()
                    self.animObjects['prevLine2'].set_speed(killSpeed)
                    del self.animObjects['currLine2']

                if newLine2Value != None:
                    w, h = newLine2Surface.get_size()
                    loop = (w > self.screenW)

                    # create a new animatable for this image
                    newLine2Anim = Animatable(newLine2Surface, self.screenW + 100,
                                              TargetXLocation.CENTERED, line2Y, newSpeed, loop=loop)
                    self.animObjects['currLine2'] = newLine2Anim

                self.currLine2 = newLine2Value

            # the service icon is not animated, it is directly replaced when changed
            self.serviceSurface = newServiceSurface
            if newServiceSurface != None:
                w1, h1 = newServiceSurface.get_size()
                newServiceAnim = Animatable(newServiceSurface, self.screenW - (w1 + 20),
                                            TargetXLocation.RIGHT, self.screenH - (h1 + 10), 0, loop=False)
                self.animObjects['currService'] = newServiceAnim
            else:
                if 'currService' in self.animObjects:
                    del self.animObjects['currService']
        return

    # This 'animate' method will move the current and previous images and
    # text lines from their current position to their target positions.
    def animate(self):
        with self.mutex:
            # background: paint it black
            self.pygameScreen.fill((0, 0, 0))

            # step though our dict of animatables and remove any that have scrolled off the screen
            delKeys = []
            for k, v in self.animObjects.items():
                remove = v.animate(self.pygameScreen)
                if remove:
                    delKeys.append(k)
            # Clean up any items that have scrolled off the screen
            for k in delKeys:
                if k in self.animObjects:
                    del self.animObjects[k]

def main():
    # default font for Windows - if a font is not found, the default system font is used.
    fontName = 'Century Gothic'

    # Parse args
    parser = argparse.ArgumentParser()
    parser.add_argument('--player_ip', dest='player_ip', type=str, help='Player IP address')
    parser.add_argument('--font', dest='fontName', type=str, help='Font to use for text lines')
    args = parser.parse_args()

    if args.player_ip == None:
        print("Missing argument: --player_ip")
        sys.exit(1)

    if args.fontName != None:
        fontName = args.fontName

    # Initialize Pygame - this auto-detects the screen size and sets up
    # a borderless full screen window
    pygame.init()

    # Define a custom event ID
    MY_TIMER_EVENT = pygame.USEREVENT + 1

    # Set the timer to post MY_TIMER_EVENT every 7000 milliseconds (7 seconds)
    pygame.time.set_timer(MY_TIMER_EVENT, 7000)

    infoObject = pygame.display.Info()

    # Set up the full screen window
    screen = pygame.display.set_mode((infoObject.current_w, infoObject.current_h), pygame.SCALED | pygame.FULLSCREEN)

    # limit the refresh rate - animations are keyed to this rate
    clock = pygame.time.Clock()
    FPS = 60

    # parameters for hiding the mouse pointer if it is idle
    IDLE_TIME_MS = 3000  # 3 seconds in milliseconds
    mouse_last_moved = pygame.time.get_ticks()
    mouse_visible = True

    # create our NowPlaying object
    nowPlaying = NowPlaying(args.player_ip, BLUPORT, screen, fontName)

    pygame.display.set_caption("Bluscreen")
    pygame.display.set_allow_screensaver(False)

    # Display loop
    running = True
    # Initial display
    nowPlaying.updateTrack()
    nowPlaying.animate()

    # main pygame loop - run until we break out
    while running:
        current_time = pygame.time.get_ticks()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == MY_TIMER_EVENT:
                # Spin up a thread to update the now playing
                # to adjust update interval, see set_timer() call above.
                t = Thread(target = nowPlaying.updateTrack)
                t.start()
            elif event.type == KEYDOWN:
                if event.key == K_RIGHT:
                    nowPlaying.skip()
                if event.key == K_SPACE:
                    nowPlaying.togglePause()
                if event.key == K_UP:
                    nowPlaying.volUp()
                if event.key == K_DOWN:
                    nowPlaying.volDown()
                if event.key == K_ESCAPE:
                    running = False
            elif event.type == pygame.MOUSEMOTION:
                mouse_last_moved = current_time
                # show the mouse again if it was hidden
                if not mouse_visible:
                    mouse_visible = True
                    pygame.mouse.set_visible(True)

            # Add a MOUSEBUTTONDOWN event handler (even if empty) to ensure clicks are processed
            elif event.type == pygame.MOUSEBUTTONDOWN:
                pass

        # Check for idle time outside the event loop
        if mouse_visible and (current_time - mouse_last_moved) > IDLE_TIME_MS:
            # hide the mouse
            mouse_visible = False
            pygame.mouse.set_visible(False)

        clock.tick(FPS)
        # Call 'animate' to update the display
        nowPlaying.animate()
        # Flip to newly drawn display
        pygame.display.flip()

    # We've broken out of the loop - Quit Pygame
    pygame.quit()

if __name__ == "__main__":
    main()
