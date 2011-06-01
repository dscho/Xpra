#!/bin/bash

BASE=`pwd`
echo "******************************************************************"
cd ${BASE}
for dist_dir in `ls -d ./dists/*/main/*`; do
		echo "******************************************************************"
		echo "** ${dist_dir}"
		dist=`basename ${dist_dir}`
		dir=`dirname ${dist_dir} | sed 's+\./+/+g'`
		distro=`dirname ${dir}`
		distro=`basename ${distro}`
		deb_path="${dir}/${dist}"
		echo "# distro=${distro}, dist=${dist}, dir=${dir}, deb_path=${deb_path}"
		cd ${BASE}/${dist_tree}/${dist_dir}
		rm Packages*
		dpkg-scanpackages . > Packages.tmp
		head -n +3 Packages.tmp > Packages.tmp2
		echo "Distribution: ${distro}" >> Packages.tmp2
		tail -n +4 Packages.tmp >> Packages.tmp2
		sed -r "s+Filename: ./+Filename: ${deb_path}/+g" < Packages.tmp2 > Packages
		rm Packages.tmp*
		bzip2 -k Packages
		gzip -c Packages > Packages.gz
		#echo "MD5Sum:" > Release
		#md5sum Packages* >> Release
done

exit 0
