def test_production_channel_layer_connection_pool_is_valid_without_connecting():
    from channels_redis.utils import create_pool, decode_hosts
    from gestion_magasin_backend import settings
    config=settings.CHANNEL_LAYERS["default"]["CONFIG"]
    pools=[create_pool(host) for host in decode_hosts(config["hosts"])]
    assert pools
    assert pools[0].connection_kwargs["socket_timeout"] > 5
    assert pools[0].connection_kwargs["socket_connect_timeout"] == 5
