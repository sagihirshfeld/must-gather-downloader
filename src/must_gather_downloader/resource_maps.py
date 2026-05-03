"""Mapping constants for must-gather resource types, aliases, and directory paths."""

_RESOURCE_ALIASES = {
    "pv": "persistentvolume",
    "sc": "storageclass",
    "obc": "objectbucketclaim",
    "ob": "objectbucket",
    "bs": "backingstore",
    "ns_store": "namespacestore",
    "bc": "bucketclass",
}

_CLUSTER_SCOPED = {
    "node": "cluster-scoped-resources/core/nodes",
    "persistentvolume": "cluster-scoped-resources/core/persistentvolumes",
    "storageclass": "cluster-scoped-resources/storage.k8s.io/storageclasses",
    "objectbucket": "cluster-scoped-resources/objectbucket.io/objectbuckets",
}

_NAMESPACED = {
    "events": ("core", "events.yaml"),
    "pod": ("core", "pods"),
    "configmap": ("core", "configmaps"),
    "secret": ("core", "secrets"),
    "deployment": ("apps", "deployments.apps"),
    "objectbucketclaim": ("objectbucket.io", "objectbucketclaims"),
    "backingstore": ("noobaa.io", "backingstores"),
    "namespacestore": ("noobaa.io", "namespacestores"),
    "bucketclass": ("noobaa.io", "bucketclasses"),
    "noobaa": ("noobaa.io", "noobaas"),
}

_CEPH_COMMANDS = {
    "cephhealth": "ceph_health_detail",
    "cephstatus": "ceph_status",
    "osdtree": "ceph_osd_tree",
    "osddump": "ceph_osd_dump",
}

_MAX_RESOURCE_SIZE = 100 * 1024

_ALL_SUPPORTED_TYPES = sorted(
    list(_CLUSTER_SCOPED.keys())
    + list(_NAMESPACED.keys())
    + list(_CEPH_COMMANDS.keys())
    + list(_RESOURCE_ALIASES.keys())
    + ["ceph"]
)
