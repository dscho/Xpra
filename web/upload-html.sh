#!/bin/bash

rsync --progress -Ccuv *css *gif *png *css *png *html root@xpra.devloop.org.uk:/var/www/xpra/htdocs/
