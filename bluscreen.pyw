import pygame
from pygame.locals import *
import requests
import argparse
from threading import Thread, Lock
import sys
import os
import io
from xml.etree import ElementTree

# Bluscreen is a 10-foot interface that displays the 'Now Playing' information
# for a BluOS player from Bluesound. This also allows some limited navigation
# (skip fwd) and volume control via the keyboard. See README.txt for more
# details.

BLUPORT = 11000

class NowPlaying:

    # This class has two sets of info, 'current' and 'prev'.
    # When the current track is updated, the old values are
    # copied to 'prev' and then scrolled off the screen.

    def resetCurrent(self):
        self.currImageSurface = None
        self.currImageBytes = None
        self.currImageX = None
        self.currImageY = None
        self.currLine1 = None
        self.currLine1X = None
        self.currLine2 = None
        self.currLine2X = None
        self.currLine1Surface = None
        self.currLine2Surface = None

    def resetPrev(self):
        self.prevImageSurface = None
        self.prevImageBytes = None
        self.prevImageY = None
        self.prevImageX = None
        self.prevLine1 = None
        self.prevLine1X = None
        self.prevLine2 = None
        self.prevLine1Surface = None
        self.prevLine2Surface = None

    # Set up defaults and calculate font size
    def __init__(self, addr, port, screen):
        self.ipaddr = addr
        self.port = port
        self.pygameScreen = screen
        self.scrollfactor = 0

        self.resetCurrent()
        self.resetPrev()

        # Mutex for swapping current/previous data
        self.mutex = Lock()

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
        self.myFont = pygame.font.SysFont('Century Gothic', self.fontSize)

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

    # do the query to the Bluesound player and track any changes since
    # the last query. This runs in a separate thread and uses a mutex when
    # updating the instance variables.
    def updateTrack(self):
        # Track what we need to swap in our critical region
        imageChanged = False
        line1Changed = False
        line2Changed = False

        # New surfaces
        newImageSurface = None
        newImageBytes = None
        newLine1Surface = None
        newLine1Value = None
        newLine2Surface = None
        newLine2Value = None

        try:
            response = requests.get(f"http://{self.ipaddr}:{self.port}/Status", timeout=2)
            if response.status_code != 200:
                print(f"Bad return status: {response.status_code}")
                sys.exit(1)
        except requests.exceptions.ConnectTimeout:
            # self.resetCurrent()
            newLine1Value = "Timeout getting status (press 'Esc' to exit)"
            newLine1Surface = self.myFont.render(newLine1Value, False, (255, 255, 255))
            with self.mutex:
                # We could not get a response, so update the 'current' info
                # with the above help text and fail out
                if self.currLine1 != newLine1Value:
                    self.prevLine1 = self.currLine1
                    self.prevLine1Surface = self.currLine1Surface
                    self.prevLine1X = self.currLine1X
                    self.currLine1 = newLine1Value
                    self.currLine1Surface = newLine1Surface
                    self.currLine1X = self.screenW + 50
                    self.currImageSurface = None
                    self.currLine2Surface = None
            return

        # Grab the XML from the Bluesound player's response
        tree = ElementTree.fromstring(response.content)

        # These are the fields that we're looking for in the XML
        info = { 'album': None, 'artist': None, 'image': None, 'name': None,
             'twoline_title1': None, 'twoline_title2': None, 'serviceName': None }

        # Copy any fields that we want from the XML into the above dict
        for child in tree:
            if child.tag in info:
                info[child.tag] = child.text

        # Check the image URL
        if info['image'] != None:
            # Sometimes the image info is a relative URL based on the Bluesound player's
            # http address, and other times it is a standalone URL that references some
            # other site.
            imgUrl = f"http://{self.ipaddr}:{self.port}/{info['image']}"
            # If the image URL starts with http: or https: then it is standalone
            if info['image'].startswith('https:') or info['image'].startswith('http:'):
                imgUrl = info['image']
            response = requests.get(imgUrl)
            if response.status_code != 200:
                # print(f"Bad return status: {response.status_code}")
                # print(f"URL: {imgUrl}")
                self.currImageSurface = None
            else:
                try:
                    # Treat the bytes like a file
                    image_file_like = io.BytesIO(response.content)

                    # See if the image has updated, if it has then we create
                    # a new pygame surface for it.
                    if response.content != self.currImageBytes:
                        imageChanged = True
                        newImageSurface = pygame.image.load(image_file_like)
                        newImageBytes = response.content
                        p_width, p_height = newImageSurface.get_size()

                        # image sizes vary, scale this one to fit our image area on the display
                        imageHeight = int(self.screenH * 0.6) - 100

                        ratio = imageHeight / p_height
                        newWidth = int(p_width * ratio)
                        newImageSurface = pygame.transform.smoothscale(newImageSurface, (newWidth, imageHeight))

                except Exception as e:
                    print(f"Failed to load image: {e}")

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
            # Special case - if nothing is playing, title1 is null.
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
                self.prevImageSurface = self.currImageSurface
                self.prevImageX = self.currImageX
                self.prevImageY = self.currImageY
                self.prevImageBytes = self.currImageBytes
                self.currImageBytes = newImageBytes
                self.currImageSurface = newImageSurface
                self.currImageY = 50
                self.currImageX = self.screenW + 100
            if line1Changed:
                self.prevLine1 = self.currLine1
                self.prevLine1Surface = self.currLine1Surface
                self.prevLine1X = self.currLine1X
                self.currLine1 = newLine1Value
                self.currLine1Surface = newLine1Surface
                self.currLine1X = self.screenW + 150
            if line2Changed:
                self.prevLine2 = self.currLine2
                self.prevLine2Surface = self.currLine2Surface
                self.prevLine2X = self.currLine2X
                self.currLine2 = newLine2Value
                self.currLine2Surface = newLine2Surface
                self.currLine2X = self.screenW + 10
        return

    # This 'animate' method will move the current and previous images and
    # text lines from their current position to their target positions.
    def animate(self):
        s_middle = self.screenW // 2
        # play with these two values if your display is too fast/slow. The
        # 'speed' affects how quickly shorter lines are moved ont he screen,
        # and 'scroll_slowdown' affects how much more slowly the longer text
        # lines scroll (ones that are wider than the screen)
        speed = 6
        scroll_slowdown = 2


        # Figure out our y values for our 2 lines and the image
        line1Y = self.screenH - (self.textHeight * 3)
        line2Y = self.screenH - (self.textHeight * 2)
        self.scrollfactor += 1

        with self.mutex:
            self.pygameScreen.fill((0, 0, 0))
            if self.currImageSurface != None:
                w1, h1 = self.currImageSurface.get_size()
                self.pygameScreen.blit(self.currImageSurface, (self.currImageX, self.currImageY))
                if self.currImageX > s_middle - (w1 // 2):
                    self.currImageX -= speed

            # Scroll the previous image off the screen if needed
            if self.prevImageSurface != None:
                w1, h1 = self.prevImageSurface.get_size()
                self.pygameScreen.blit(self.prevImageSurface, (self.prevImageX, self.prevImageY))
                if self.prevImageX > -(w1 + 10):
                    self.prevImageX -= speed * 3


            # The text lines start off the right hand side of the screen and end up centered.
            # Lines that are longer than the width of the screen are scrolled more slowly
            if self.currLine1Surface != None:
                w1, h1 = self.currLine1Surface.get_size()
                self.pygameScreen.blit(self.currLine1Surface, (self.currLine1X, line1Y))
                if w1 > self.screenW:
                    if self.currLine1X > - (w1):
                        if self.scrollfactor % scroll_slowdown == 0:
                            self.currLine1X -= speed
                    else:
                        self.currLine1X = self.screenW
                else:
                    if self.currLine1X > s_middle - (w1 // 2):
                        self.currLine1X -= speed

            # The previous text lines start out centered, then scroll off quickly to the
            # left hand side of the screen.
            if self.prevLine1Surface != None:
                w1, h1 = self.prevLine1Surface.get_size()
                self.pygameScreen.blit(self.prevLine1Surface, (self.prevLine1X, line1Y))
                if self.prevLine1X > - (w1):
                    self.prevLine1X -= speed * 3

           # Like the line 1 surfaces, line 2 starts to the right of the screen and ands
           # up centered for shorter lines, and are scrolled more slowly for longer lines.
            if self.currLine2Surface != None:
                w1, h1 = self.currLine2Surface.get_size()
                self.pygameScreen.blit(self.currLine2Surface, (self.currLine2X, line2Y))
                if w1 > self.screenW:

                    # Check if the line has scrolled off the screen and reset at right if so
                    if self.currLine2X > - (w1):
                        if self.scrollfactor % scroll_slowdown == 0:
                            self.currLine2X -= speed
                    else:
                        # reset X position to far right of screen
                        self.currLine2X = self.screenW
                else:
                    if self.currLine2X > s_middle - (w1 // 2):
                        self.currLine2X -= speed

            if self.prevLine2Surface != None:
                w1, h1 = self.prevLine2Surface.get_size()
                self.pygameScreen.blit(self.prevLine2Surface, (self.prevLine2X, line2Y))
                if self.prevLine2X > -(w1 + 10):
                    self.prevLine2X -= speed * 3

def main():

    playerIp = None

    # Parse args
    parser = argparse.ArgumentParser()
    parser.add_argument('--player_ip', dest='player_ip', type=str, help='Player IP address')
    args = parser.parse_args()

    if args.player_ip == None:
        print("Missing argument: --player_ip")
        sys.exit(1)

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

    # create our NowPLaying object
    nowPlaying = NowPlaying(args.player_ip, BLUPORT, screen)

    pygame.display.set_caption("BlueScreen")
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
                if not mouse_visible:
                    mouse_visible = True
                    pygame.mouse.set_visible(True)

            # Add a MOUSEBUTTONDOWN event handler (even if empty) to ensure clicks are processed
            elif event.type == pygame.MOUSEBUTTONDOWN:
                pass

        # Check for idle time outside the event loop
        if mouse_visible and (current_time - mouse_last_moved) > IDLE_TIME_MS:
            mouse_visible = False
            pygame.mouse.set_visible(False)

        clock.tick(FPS)
        # Call 'animate' to update the display
        nowPlaying.animate()
        # Flip to newly drawn display
        pygame.display.flip()

    # Quit Pygame
    pygame.quit()

if __name__ == "__main__":
    main()