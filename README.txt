Bluscreen is an 'across the room' now-playing display for Bluesound players.

Quick start:
 - Clone this repo
 - add any missing Python modules (likely just pygame and requests)
 - you may need to select a new font for the display base don your platform of choice. By
   default this uses 'Century Gothic' but this is not available everywhere, for a
   Raspberry Pi deployment I was using FreeSans
 - run the display using 'python3 bluscreen.pyw --player_ip #.#.#.#'

While the display is running:
 - 'Esc' will quit the display
 - Spacebar will toggle play/pause for the current track
 - Right arrow will skip to the next track
 - Up and down arrows will raise and lower player volume

It is recommended that your player is set up with a static IP address so you
don't have to keep finding the player IP manually. Your player's IP address
can be found in the Bluesound client software under 'Help -> Diagnostics'.

This program uses the Bluesound custom integration API that is described
here: https://bluos.io/wp-content/uploads/2025/06/BluOS-Custom-Integration-API_v1.7.pdf

This program works with the BluOS ecosystem, it is not an official product of
Lenbrook or Bluesound.

This program is not perfect - improvements are welcome. I am fairly new to github so any suggestions
to make this repo more useful wold be appreciated. Have fun!

