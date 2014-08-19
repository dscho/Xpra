#!/bin/sh
PUBLISH_BASE=image
echo
echo "*******************************************************************************"
if [ ! -d "$PUBLISH_BASE/Xpra.app" ]; then
	echo "$PUBLISH_BASE/Xpra.app is missing!"
	echo "run make-app.sh first"
	exit 1
fi

export PYTHONPATH="$PUBLISH_BASE/Xpra.app/Contents/Resources/lib/python/"
VERSION=`python -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
#prefer revision directly from svn:
REVISION=`svnversion -n .. | awk -F: '{print $2}'`
if [ -z "${REVISION}" ]; then
	#fallback to using revision recorded in build info
	REVISION=`python -c "from xpra import src_info;import sys;sys.stdout.write(src_info.REVISION)"`
fi
PKG_NAME="Xpra-$VERSION-r$REVISION.pkg"
echo "Creating $PKG_NAME"

rm -fr image/*pkg

echo "Creating PKG"
/Developer/usr/bin/packagemaker --verbose --doc xpra.pmdoc --out image/Xpra.pkg -i org.xpra

if [ ! -e image/Xpra.pkg ] ; then
  echo FAILED TO CREATE PKG
  exit 1
fi

echo "Size of package: `du -sh image/Xpra.pkg`"

echo "Done"
echo "*******************************************************************************"
echo
