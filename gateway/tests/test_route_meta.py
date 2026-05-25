from radicalbit_ai_gateway.route_meta import route_meta


def test_attaches_meta_dict():
    @route_meta(entity_type='PROJECT', response_uuid_field='uuid')
    def handler():
        pass

    assert handler._route_meta == {
        'entity_type': 'PROJECT',
        'response_uuid_field': 'uuid',
    }


def test_returns_same_function_object():
    def original():
        pass

    wrapped = route_meta(foo='bar')(original)

    assert wrapped is original


def test_empty_kwargs():
    @route_meta()
    def handler():
        pass

    assert handler._route_meta == {}
