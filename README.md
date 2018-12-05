# sanus-hha-client

## Sound Fix
`sudo amixer -c 0 cset numid=3 0`

Sound Files
* alsa.conf - make sure defaults are 0
* ~/.asoundrc
* Make sure you make proper sound card selection
* Change `alsamixer` to have 100% volume if it sounds low

Make sure that the .asoundrc file looks like this.


```sh
pcm.!default {
        type plug
        slave {
            pcm "hw:0,0"
        }
}

ctl.!default {
        type hw
        card 0
}
```
