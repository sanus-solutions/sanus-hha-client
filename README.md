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
## MongoDB Structure
```sh
In collections: Staff Docs Structure (1/24/19)

{staff_id, string}
{staff_title, string}
{staff_department, string}
{staff_address, string}
{staff_birthdate, string}
{staff_phoneNum, string}

In collections: Node Docs Structure (1/24/19)

{node_id, string}
{node_type, string}
{node_unit, string}
{node_roomNum, string}


# For Staff

db.hospital1.insertOne({staff_id: "klaus",staff_title: "Nurse",staff_department: "Oncology",staff_address: "China",staff_birthdate: "08/01/1993",staff_phoneNum: "4046323234"})

# For Nodes
db.hospital1.insertOne({node_id: "0", node_type:"ENTRY", node_unit:"ER", node_roomNum: "2500"})

```