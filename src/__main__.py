import sys
import json
from specklepy.api import operations
from specklepy.objects.geometry import Mesh
from specklepy.objects.other import BlockDefinition, BlockInstance, Transform, Collection, RenderMaterial
from specklepy.transports.server import ServerTransport
from specklepy.api.client import SpeckleClient
from specklepy.api.credentials import (get_local_accounts, get_default_account)
import numpy as np

file = sys.argv[1]

client = SpeckleClient("speckle.xyz")
all_accounts = get_local_accounts()
selected_account = all_accounts[0]
client.authenticate_with_token(token=selected_account.token)
account = get_default_account()

with open(file) as json_data:
    d = json.load(json_data)
    json_data.close()

root = d["structure"]["root"]
entry = d["structure"]["tree"][str(root)]

def traverse(tree, solids, obj, route):
    type =  obj["class"]
    if type not in ("CC_AssemblyRoot", "CC_Assembly", "CC_Part", "CC_ProductReference", "CC_ProductReferenceET"):
        return
    
    print(obj["name"])

    if "coordinateSystem" in obj:
        csys = obj["coordinateSystem"]
        p = csys[0]
        x = csys[1]
        y = csys[2]
        z = csys[3]
        obj["matrix"] = np.array([
            [x[0], y[0], z[0], p[0]],
            [x[1], y[1], z[1], p[1]],
            [x[2], y[2], z[2], p[2]],
            [0,    0,    0,    1]
        ])
    
    children = []
    if "link" in obj:        
        link = tree[str(obj["link"])]
        print("  link: " + link["name"] + " " + link["class"])

        matrix = np.identity(4)
        for id in route + [obj["id"]]:
            el = tree[str(id)]
            try:
                matrix = matrix @ el["matrix"]
            except KeyError:
                pass
            
        print(matrix)
        transform = Transform(matrix=matrix.flatten().tolist(), units="meters")

        for solid in link["solids"]:
            try:
                container = next(x for x in solids if x["id"] == solid)
                instance = BlockInstance(definition=container["definition"], transform=transform)
                children.append(instance)
            except KeyError:
                pass

    try:
        if len(obj["children"]) > 0:
            for childId in obj["children"]:
                child = traverse(tree, solids, tree[str(childId)], route + [obj["id"]])
                if child is not None:
                    children.append(child)
    except KeyError:
        pass

    product = Collection(name=obj["name"], elements=children)
    return product

def to_argb_int(rgba_color: list[float]) -> int:
    argb_color = rgba_color[-1:] + rgba_color[:3]
    int_color = [int(val * 255) for val in argb_color]
    return int.from_bytes(int_color, byteorder="big", signed=True)

# Create re-usable block definitions for each container/solid
for container in d["graphic"]["containers"]:
    verts = []
    faces = []
    rgb = container["properties"]["material"]["color"]
    opacity = container["properties"]["material"]["opacity"]
    argb = to_argb_int([rgb[0] / 255, rgb[1] / 255, rgb[2] / 255])
    try:
        for mesh in container["meshes"]:
            vert_len = len(verts) // 3
            for vertex in mesh["vertices"]:
                verts.append(vertex)
            indices = mesh["indices"]
            index_len = len(indices)
            for x in range(index_len // 3):
                faces.append(3)
                faces.append(indices[x * 3] + vert_len)
                faces.append(indices[x * 3 + 1] + vert_len)
                faces.append(indices[x * 3 + 2] + vert_len)
        mesh = Mesh(vertices=verts, faces=faces, colors=[])
        material = RenderMaterial()
        material.name = "foo"
        material.diffuse = argb
        mesh["renderMaterial"] = material
        container["definition"] = BlockDefinition(name="Solid" + str(container["id"]), geometry=[mesh])
    except KeyError:
        pass

rootAsm = traverse(d["structure"]["tree"], d["graphic"]["containers"], entry, [])
new_stream_id = client.stream.create(name=file)
new_stream = client.stream.get(id=new_stream_id)
transport = ServerTransport(client=client, stream_id=new_stream_id)
hash = operations.send(base=rootAsm, transports=[transport])
commid_id = client.commit.create(stream_id=new_stream_id, object_id=hash)

print("done")