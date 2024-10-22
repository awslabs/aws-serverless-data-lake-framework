#!/usr/bin/env python3

import aws_cdk as cdk

from foundations import Foundations

app = cdk.App()
stack = cdk.Stack(app, "FoundationsStack")
Foundations(stack, "foundations")

app.synth()
