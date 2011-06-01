#!/bin/bash

rsync --progress -Ccuvr patches/*  root@xpra.devloop.org.uk:/var/www/xpra/htdocs/patches/
