def traverse_config(object, configver):
        path = configver[1]
        lookup = object
        for key in path:
            lookup = lookup[key]
        return lookup
