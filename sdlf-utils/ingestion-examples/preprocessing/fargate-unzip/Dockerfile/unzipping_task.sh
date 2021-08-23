#!/usr/bin/env bash
set -e

if [ -z "$SRC_BUCKET" ]
  then
    echo "Please set SRC_BUCKET environment variable"
    exit
fi
if [ -z "$DEST_BUCKET" ]
  then
    echo "Please set DEST_BUCKET environment variable"
    exit
fi
if [ -z "$SRC_KEY" ]
  then
    echo "Please set SRC_KEY environment variable"
    exit
fi

echo "Unzipping s3://$SRC_BUCKET/$SRC_KEY to s3://$DEST_BUCKET/$SRC_KEY"
/usr/local/bin/aws s3 cp s3://$SRC_BUCKET/$SRC_KEY - | gunzip | /usr/local/bin/aws  s3 cp - s3://$DEST_BUCKET/$(dirname $SRC_KEY)/$(basename $SRC_KEY .gz)
echo "Finished unzipping - File located at s3://$DEST_BUCKET/$SRC_KEY"
