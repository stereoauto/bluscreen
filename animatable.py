import pygame
from enum import Enum
from pygame.locals import *

# Items scroll from right to left, this represents where
# we want the item to stop.
class TargetXLocation(Enum):
    CENTERED = 1
    RIGHT = 2
    LEFT = 3
    OFFSCREEN = 4

# A side-scrolling animatable pygame surface
class Animatable:

    # Constructor for a new Animatable - arguments:
    #   surface: a text or image pygame surface
    #   currX:   current X position (at creation)
    #   wantedX: wanted X pos (using above Enum)
    #   currY:   Y position for this item (side scrolling)
    #   speed:   X increment for scrolling
    #   loop:    do we want to loop this value (for items wider than the screen)
    # value
    def __init__(self, surface, currX, wantedXEnum, currY, speed, loop=False):
        self.surface = surface
        self.w, self.h = self.surface.get_size()
        self.currX = currX
        self.wantedXEnum = wantedXEnum
         # Calculated when needed
        self.wantedX = None
        self.currY = currY
        self.speed = speed
        if loop:
            # Looped items move a bit slower
            if self.speed > 1:
                self.speed -= 1
        self.alive = True
        self.loop = loop

    # Look at our current state and decide if we need to move this item
    # towards its wanted position
    def animate(self, screen):
        screenW, screenH = screen.get_size()
        third = screenW // 3

        # See if we need to compute our wanted X based on a new location
        if self.wantedX == None:
            if self.wantedXEnum == TargetXLocation.CENTERED:
                self.wantedX = (screenW // 2) - (self.w // 2)
            elif self.wantedXEnum == TargetXLocation.RIGHT:
                self.wantedX = (screenW - (self.w + 50))
            elif self.wantedXEnum == TargetXLocation.LEFT:
                self.wantedX = 50
            elif self.wantedXEnum == TargetXLocation.OFFSCREEN:
                self.wantedX = -(self.w + 50)

        if self.loop == False:
            if self.currX > self.wantedX:
                self.currX -= self.speed
        else:
            # Looping a longer title
            self.currX -= self.speed

            if self.currX < -self.w and self.alive == True:
                # Loop back to the right hand side of the screen
                self.currX = self.currX + self.w + (2 * third)

        screen.blit(self.surface, (self.currX, self.currY))

        if self.loop == True and self.alive == True:
            # blit a second copy of the line
            # If the line is occupying less than 1/3 of the screen width, start
            # a new copy at the edge of the screen.
            if (self.currX + self.w) < (third):
                screen.blit(self.surface, (self.currX + self.w + (2 * third), self.currY))

        # if the item has scrolled off the left hand side of the screen,
        # return true
        if self.alive == True and self.currX < -self.w:
            return True
        else:
            return False

    # Set a new speed for the item
    def set_speed(self, newspeed):
        self.speed = newspeed

    # Indicate that this item is no longer wanted - speed it up and set
    # a new X pos to be off the screen.
    def kill(self):
        self.alive = False
        w, h = self.surface.get_size()
        self.wantedXEnum = TargetXLocation.OFFSCREEN
        self.wantedX = None
