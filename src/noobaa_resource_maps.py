"""Mapping constants for NooBaa-specific resource types, aliases, and directory paths."""

_NOOBAA_NAMESPACED = {
    "objectbucketclaim": ("objectbucket.io", "objectbucketclaims"),
    "backingstore": ("noobaa.io", "backingstores"),
    "namespacestore": ("noobaa.io", "namespacestores"),
    "bucketclass": ("noobaa.io", "bucketclasses"),
    "noobaa": ("noobaa.io", "noobaas"),
}

_NOOBAA_CLUSTER_SCOPED = {
    "objectbucket": "cluster-scoped-resources/objectbucket.io/objectbuckets",
}

_NOOBAA_RESOURCE_ALIASES = {
    "obc": "objectbucketclaim",
    "ob": "objectbucket",
    "bs": "backingstore",
    "ns_store": "namespacestore",
    "bc": "bucketclass",
}

_ALL_NOOBAA_TYPES = sorted(
    ["status", "db_list", "diagnostics", "logs", "cnpg"]
    + list(_NOOBAA_NAMESPACED.keys())
    + list(_NOOBAA_CLUSTER_SCOPED.keys())
    + list(_NOOBAA_RESOURCE_ALIASES.keys())
)
