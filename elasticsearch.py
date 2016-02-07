#!/usr/bin/python
from troposphere import Template, Ref, Tags, Join, Base64, GetAtt, Output

from troposphere.ec2 import *
from troposphere.autoscaling import Metadata
from troposphere.cloudformation import *

import boto.cloudformation
import boto.ec2
import fnmatch
import sys
import time

# Stack that creates an elastic search instance
def create():

	es = Template()

	es.add_description("Stack defining the elasticsearch instance")

	# Get latest AMIs
	def getAMI():
		AMIMap = {}
		regions = boto.ec2.regions()
		for region in regions:
		        if not fnmatch.fnmatch(region.name,"cn-*") and not fnmatch.fnmatch(region.name,"*gov*"):
						print("Getting latest AMZN linux AMI in %s" % region.name)
		                ec2conn = boto.ec2.connect_to_region(region.name)
		                images = ec2conn.get_all_images(owners=["amazon"], filters={"name": "amzn-ami-hvm-*.x86_64-gp2"})
		                latestDate = ""
		                latestAMI = ""
		                for image in images:
		                        if image.creationDate > latestDate:
		                                latestDate = image.creationDate
		                                latestAMI = image.id
	                	AMIMap[region.name] = {"id": latestAMI}
		return AMIMap

	# Create AMI Map
	# es.add_mapping("AMIMap",getAMI())

	# Create es VPC
	esVPC = es.add_resource(
		VPC(
			"esVPC",
			CidrBlock="10.0.0.0/16",
			Tags=Tags(
				Name="esVPC"
			)
		)
	)

	# Create es IGW
	esIGW = es.add_resource(
		InternetGateway(
			"esIGW"
		)
	)

	# Attach IGW to VPC
	esIGWAttachment = es.add_resource(
		VPCGatewayAttachment(
			"esIGWAttachment",
			VpcId=Ref(esVPC),
			InternetGatewayId=Ref(esIGW)
		)
	)

	# Create es Subnet
	esSubnet = es.add_resource(
		Subnet(
			"esSubnet",
			CidrBlock="10.0.0.0/24",
			VpcId=Ref(esVPC)
		)
	)

	# Create es RTB
	esRTB = es.add_resource(
		RouteTable(
			"esRTB",
			VpcId=Ref(esVPC)
		)
	)

	# Create route to IGW
	esDefaultRoute = es.add_resource(
		Route(
			"esDefaultRoute",
			DependsOn="esIGWAttachment",
			GatewayId=Ref(esIGW),
			DestinationCidrBlock="0.0.0.0/0",
			RouteTableId=Ref(esRTB)
		)
	)

	# Associate RTB with Subnet
	esSubnetRTBAssociation = es.add_resource(
		SubnetRouteTableAssociation(
			"esSubnetRTBAssociation",
			SubnetId=Ref(esSubnet),
			RouteTableId=Ref(esRTB)
		)
	)

	# Create es Security Group
	esSecurityGroup = es.add_resource(
		SecurityGroup(
			"esSecurityGroup",
			GroupDescription="Allow inbound access on port 22 and 9200",
			SecurityGroupIngress=[
				SecurityGroupRule(
					IpProtocol="tcp",
					FromPort="22",
					ToPort="22",
					CidrIp="0.0.0.0/0"
				),
				SecurityGroupRule(
					IpProtocol="tcp",
					FromPort="9200",
					ToPort="9200",
					CidrIp="0.0.0.0/0"
				)
			],
			VpcId=Ref(esVPC)
		)
	)

	# Create es instance metadata
	esInstanceMetadata = Metadata(
		Init(
			# Use ConfigSets to ensure GPG key and repo file are in place first
			# before trying to install elasticsearch
			InitConfigSets(
				ordered=["first","second"]
			),
			first=InitConfig(
				files=InitFiles(
					{
						# cfn-hup notices when the cloudformation stack is changed
						"/etc/cfn/cfn-hup.conf": InitFile(
							content=Join("",
								[
									"[main]\n",
									"stack=",Ref("AWS::StackName"),"\n",
									"region=",Ref("AWS::Region"),"\n"
								]
							),
							mode="000400",
							owner="root",
							group="root"
						),
						# cfn-hup will then trigger cfn-init to run.
						# This lets us update the instance just by updating the stack
						"/etc/cfn/hooks.d/cfn-auto-reloader.conf": InitFile(
							content=Join("",
								[
									"[cfn-auto-reloader-hook]\n",
									"triggers=post.update\n",
									"path=Resources.esInstance.Metadata\n",
									"action=/opt/aws/bin/cfn-init -v --stack ", Ref("AWS::StackName"), " ",
									"--resource esInstance ",
									"--region ", Ref("AWS::Region"), " ",
									"--c ordered\n"
									"runas=root\n"
								]
							),
							mode="000400",
							owner="root",
							group="root"
						),
						# repo file for elastic search
						"/etc/yum.repos.d/elasticsearch.repo": InitFile(
							content=Join("",
								[
									"[elasticsearch-2.x]\n",
									"name=Elasticsearch repository for 2.x packages\n",
									"baseurl=http://packages.elastic.co/elasticsearch/2.x/centos\n",
									"gpgcheck=1\n",
									"gpgkey=http://packages.elastic.co/GPG-KEY-elasticsearch\n",
									"enabled=1\n"
								]
							),
							mode="000400",
							owner="root",
							group="root"
						)
					}
				),
				commands={
					# Install elasticsearch key so package will install
					"installGPG": {
						"command": "rpm --import https://packages.elastic.co/GPG-KEY-elasticsearch"
					}
				}
			),
			second=InitConfig(
				packages={
					"yum": {
						# Install elasticsearch
						"elasticsearch": [],
					}
				},
				commands={
					# Enable external access to elasticsearch
					"listenOnAllinterfaces": {
						"command": "echo \"network.host: 0.0.0.0\" >> /etc/elasticsearch/elasticsearch.yml"
					}
				},
				services={
					"sysvinit": InitServices(
						{
							"elasticsearch": InitService(
								enabled=True,
								ensureRunning=True
							),
							"cfn-hup": InitService(
								enabled=True,
								ensureRunning=True,
								files=[
									"/etc/cfn/cfn-hup.conf",
									"/etc/cfn/hooks.d/cfn-auto-reloader.conf"
								]
							)
						}
					)
				}
			)
		)
	)

	# Create es Instance
	esInstance = es.add_resource(
		Instance(
			"esInstance",
			# ImageId=FindInMap("AMIMap",Ref("AWS::Region"),"id"),
			ImageId="ami-48d38c2b",
			InstanceType="t2.micro",
			KeyName="aws_rkelledy_test", # TODO remove this after testing
			Metadata=esInstanceMetadata,
			UserData=Base64(
				Join("",
					[
						"#!/bin/bash\n",
						"/opt/aws/bin/cfn-init -v ",
						"--stack ", Ref("AWS::StackName"), " ",
						"--resource esInstance ",
						"--region ", Ref("AWS::Region"), " ",
						"-c ordered"
					]
				)
			),
			NetworkInterfaces=[
				NetworkInterfaceProperty(
					GroupSet=[
						Ref(esSecurityGroup)
					],
					AssociatePublicIpAddress="true",
					DeviceIndex="0",
					DeleteOnTermination="true",
					SubnetId=Ref(esSubnet),

				)
			],
			Tags=Tags(
				Name="esInstance"
			)
		)
	)

	# Output address
	es.add_output(
		[Output
			("esAddress",
			Description="Elastic Search address",
			Value=Join("",
				[
					"http://", GetAtt("esInstance", "PublicIp"), ":9200/"
				]
			)
			)
		]
	)
	return es

# Connect to cloudformation
cfnConnection = boto.cloudformation.connect_to_region("ap-southeast-2")

# Create stack template
stack = create()

# Create stack
cfnConnection.create_stack(
			stack_name="elasticsearch",
			template_body=stack.to_json()
)

# Wait for stack to create so we can output the URL
print("Waiting for frontend stack creation")
stackResult = cfnConnection.describe_stacks("elasticsearch")
print("."),
while stackResult[0].stack_status not in ("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"):
	sys.stdout.flush()
        time.sleep(10)
	print("."),
        stackResult = cfnConnection.describe_stacks("elasticsearch")

print("done.")
print stackResult
