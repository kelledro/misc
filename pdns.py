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

# set region
region = "us-east-1"
stackName = "pdns"

# Stack that creates pdns instances in 2 azs
def create():

    pdns = Template()

    pdns.add_description("Stack defining the pdns instances")

    # Get latest AMIs
    def getAMI(region):
        AMIMap = {}
        print("Getting latest AMZN linux AMI in %s" % region)
        ec2conn = boto.ec2.connect_to_region(region)
        images = ec2conn.get_all_images(owners=["amazon"], filters={"name": "amzn-ami-hvm-*.x86_64-gp2"})
        latestDate = ""
        latestAMI = ""
        for image in images:
            if image.creationDate > latestDate:
                latestDate = image.creationDate
                latestAMI = image.id
        AMIMap[region] = {"id": latestAMI}
        return AMIMap

    # Create AMI Map
    pdns.add_mapping("AMIMap",getAMI(region))

    # Create pdns VPC
    pdnsVPC = pdns.add_resource(
        VPC(
            "pdnsVPC",
            CidrBlock="10.0.0.0/16",
            Tags=Tags(
                Name="pdnsVPC"
            )
        )
    )

    # Create pdns IGW
    pdnsIGW = pdns.add_resource(
        InternetGateway(
            "pdnsIGW"
        )
    )

    # Attach IGW to VPC
    pdnsIGWAttachment = pdns.add_resource(
        VPCGatewayAttachment(
            "pdnsIGWAttachment",
            VpcId=Ref(pdnsVPC),
            InternetGatewayId=Ref(pdnsIGW)
        )
    )

    # Create pdns SubnetA
    pdnsSubnetA = pdns.add_resource(
        Subnet(
            "pdnsSubnetA",
            CidrBlock="10.0.1.0/24",
            VpcId=Ref(pdnsVPC),
            AvailabilityZone=Join("", [region, "a"])
        )
    )

    # Create pdns SubnetB
    pdnsSubnetB = pdns.add_resource(
        Subnet(
            "pdnsSubnetB",
            CidrBlock="10.0.2.0/24",
            VpcId=Ref(pdnsVPC),
            AvailabilityZone=Join("", [region, "b"])
        )
    )

    # Create pdns RTB
    pdnsRTB = pdns.add_resource(
        RouteTable(
            "pdnsRTB",
            VpcId=Ref(pdnsVPC)
        )
    )

    # Create route to IGW
    pdnsDefaultRoute = pdns.add_resource(
        Route(
            "pdnsDefaultRoute",
            DependsOn="pdnsIGWAttachment",
            GatewayId=Ref(pdnsIGW),
            DestinationCidrBlock="0.0.0.0/0",
            RouteTableId=Ref(pdnsRTB)
        )
    )

    # Associate RTB with SubnetA
    pdnsSubnetRTBAssociation = pdns.add_resource(
        SubnetRouteTableAssociation(
            "pdnsSubnetRTBAssociationA",
            SubnetId=Ref(pdnsSubnetA),
            RouteTableId=Ref(pdnsRTB)
        )
    )

    # Associate RTB with SubnetB
    pdnsSubnetRTBAssociation = pdns.add_resource(
        SubnetRouteTableAssociation(
            "pdnsSubnetRTBAssociationB",
            SubnetId=Ref(pdnsSubnetB),
            RouteTableId=Ref(pdnsRTB)
        )
    )

    # Create pdns Security Group
    pdnsSecurityGroup = pdns.add_resource(
        SecurityGroup(
            "pdnsSecurityGroup",
            GroupDescription="Allow inbound DNS access",
            SecurityGroupIngress=[
                SecurityGroupRule(
                    IpProtocol="udp",
                    FromPort="53",
                    ToPort="53",
                    CidrIp="0.0.0.0/0"
                ),
                SecurityGroupRule(
                    IpProtocol="tcp",
                    FromPort="53",
                    ToPort="53",
                    CidrIp="0.0.0.0/0"
                )
            ],
            VpcId=Ref(pdnsVPC)
        )
    )

    # Create pdns instance metadata
    pdnsInstanceMetadata = Metadata(
        Init(
            # Use ConfigSets to ensure GPG key and repo file are in place
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
                                    "path=Resources.pdnsInstance.Metadata\n",
                                    "action=/opt/aws/bin/cfn-init -v --stack ", Ref("AWS::StackName"), " ",
                                    "--resource pdnsInstance ",
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

    # Create pdns Instance
    pdnsInstance = pdns.add_resource(
        Instance(
            "pdnsInstance",
            ImageId=FindInMap("AMIMap",Ref("AWS::Region"),"id"),
            InstanceType="t2.micro",
            Metadata=pdnsInstanceMetadata,
            UserData=Base64(
                Join("",
                    [
                        "#!/bin/bash\n",
                        "/opt/aws/bin/cfn-init -v ",
                        "--stack ", Ref("AWS::StackName"), " ",
                        "--resource pdnsInstance ",
                        "--region ", Ref("AWS::Region"), " ",
                        "-c ordered"
                    ]
                )
            ),
            NetworkInterfaces=[
                NetworkInterfaceProperty(
                    GroupSet=[
                        Ref(pdnsSecurityGroup)
                    ],
                    AssociatePublicIpAddress="true",
                    DeviceIndex="0",
                    DeleteOnTermination="true",
                    SubnetId=Ref(pdnsSubnet),

                )
            ],
            Tags=Tags(
                Name="pdnsInstance"
            )
        )
    )

    # Output address
    pdns.add_output(
        [Output
            ("pdnsAddress",
            Description="Elastic Search address",
            Value=Join("",
                [
                    "http://", GetAtt("pdnsInstance", "PublicIp"), ":9200/"
                ]
            )
            )
        ]
    )
    return pdns

stack = create()
print stack.to_json()
