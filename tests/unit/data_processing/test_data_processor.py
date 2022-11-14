import itertools
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

import numpy as np
import pandas as pd
import pytest
from rdt.errors import Error
from rdt.errors import NotFittedError as RDTNotFittedError
from rdt.transformers import FloatFormatter, LabelEncoder

from sdv.constraints.errors import (
    AggregateConstraintsError, FunctionError, MissingConstraintColumnError)
from sdv.constraints.tabular import Positive, ScalarRange
from sdv.data_processing.data_processor import DataProcessor
from sdv.data_processing.errors import NotFittedError
from sdv.data_processing.numerical_formatter import NumericalFormatter
from sdv.metadata.single_table import SingleTableMetadata


class TestDataProcessor:

    @patch('sdv.data_processing.data_processor.Constraint')
    def test__load_constraints(self, constraint_mock):
        """Test the ``_load_constraints`` method.

        The method should take all the constraints in the passed metadata and
        call the ``Constraint.from_dict`` method on them.

        # Setup
            - Patch the ``Constraint`` module.
            - Mock the metadata to have constraint dicts.

        # Side effects:
            - ``self._constraints`` should be populated.
        """
        # Setup
        data_processor = Mock()
        constraint1 = Mock()
        constraint2 = Mock()
        constraint1_dict = {
            'constraint_name': 'Inequality',
            'low_column_name': 'col1',
            'high_column_name': 'col2'
        }
        constraint2_dict = {
            'constraint_name': 'ScalarInequality',
            'column_name': 'col1',
            'relation': '<',
            'value': 10
        }
        constraint_mock.from_dict.side_effect = [
            constraint1, constraint2
        ]
        data_processor.metadata._constraints = [constraint1_dict, constraint2_dict]

        # Run
        loaded_constraints = DataProcessor._load_constraints(data_processor)

        # Assert
        assert loaded_constraints == [constraint1, constraint2]
        constraint_mock.from_dict.assert_has_calls(
            [call(constraint1_dict), call(constraint2_dict)])

    def test__update_numerical_transformer(self):
        """Test the ``_update_numerical_transformer`` method.

        The ``_transformers_by_sdtype`` dict should be updated based on the
        ``learn_rounding_scheme`` and ``enforce_min_max_values`` parameters.

        Input:
            - learn_rounding_scheme set to False.
            - enforce_min_max_values set to False.
        """
        # Setup
        data_processor = Mock()

        # Run
        DataProcessor._update_numerical_transformer(data_processor, False, False)

        # Assert
        transformer_dict = data_processor._transformers_by_sdtype.update.mock_calls[0][1][0]
        transformer = transformer_dict.get('numerical')
        assert transformer.learn_rounding_scheme is False
        assert transformer.enforce_min_max_values is False

    @patch('sdv.data_processing.data_processor.rdt')
    @patch('sdv.data_processing.data_processor.DataProcessor._load_constraints')
    @patch('sdv.data_processing.data_processor.DataProcessor._update_numerical_transformer')
    def test___init__(self, update_transformer_mock, load_constraints_mock, mock_rdt):
        """Test the ``__init__`` method.

        Setup:
            - Patch the ``Constraint`` module.

        Input:
            - A mock for metadata.
            - learn_rounding_scheme set to True.
            - enforce_min_max_values set to False.
        """
        # Setup
        metadata_mock = Mock()
        constraint1_dict = {
            'constraint_name': 'Inequality',
            'low_column_name': 'col1',
            'high_column_name': 'col2'
        }
        constraint2_dict = {
            'constraint_name': 'ScalarInequality',
            'column_name': 'col1',
            'relation': '<',
            'value': 10
        }
        metadata_mock._constraints = [constraint1_dict, constraint2_dict]

        # Run
        data_processor = DataProcessor(
            metadata=metadata_mock,
            learn_rounding_scheme=True,
            enforce_min_max_values=False)

        # Assert
        assert data_processor.metadata == metadata_mock
        update_transformer_mock.assert_called_with(True, False)
        load_constraints_mock.assert_called_once()
        assert data_processor._hyper_transformer == mock_rdt.HyperTransformer.return_value

    def test___init___without_mocks(self):
        """Test the ``__init__`` method without using mocks.

        Setup:
            - Create ``SingleTableMetadata`` instance with one column and one constraint.

        Input:
            - The ``SingleTableMetadata``.
        """
        # Setup
        metadata = SingleTableMetadata()
        metadata.add_column('col', sdtype='numerical')
        metadata.add_constraint('Positive', column_name='col')

        # Run
        instance = DataProcessor(metadata=metadata)

        # Assert
        assert isinstance(instance.metadata, SingleTableMetadata)
        assert instance.metadata._columns == {'col': {'sdtype': 'numerical'}}
        assert instance.metadata._constraints == [
            {'constraint_name': 'Positive', 'column_name': 'col'}
        ]
        assert len(instance._constraints) == 1
        assert isinstance(instance._constraints[0], Positive)

    def test_filter_valid(self):
        """Test that we are calling the ``filter_valid`` of each constraint over the data."""
        # Setup
        data = pd.DataFrame({
            'numbers': [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
            'range': [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
        })
        instance = Mock()
        scalar_range = ScalarRange('range', low_value=0, high_value=90, strict_boundaries=True)
        positive = Positive('numbers')
        instance._constraints = [scalar_range, positive]

        # Run
        data = DataProcessor.filter_valid(instance, data)

        # Assert
        expected_data = pd.DataFrame({
            'numbers': [1, 2, 3, 4, 5, 6, 7, 8],
            'range': [10, 20, 30, 40, 50, 60, 70, 80]
        }, index=[1, 2, 3, 4, 5, 6, 7, 8])
        pd.testing.assert_frame_equal(expected_data, data)

    def test_to_dict_from_dict(self):
        """Test that ``to_dict`` and ``from_dict`` methods are inverse to each other.

        Run ``from_dict`` on a dict generated by ``to_dict``, and ensure the result
        is the same as the original DataProcessor.

        Setup:
            - A DataProcessor with all its attributes set.

        Input:
            - ``from_dict`` takes the output of ``to_dict``.

        Output:
            - The original DataProcessor instance.
        """
        # Setup
        metadata = SingleTableMetadata()
        metadata.add_column('col', sdtype='numerical')
        metadata.add_constraint('Positive', column_name='col')
        instance = DataProcessor(metadata=metadata)
        instance._constraints_to_reverse = [Positive('col')]

        # Run
        new_instance = instance.from_dict(instance.to_dict())

        # Assert
        assert instance.metadata.to_dict() == new_instance.metadata.to_dict()
        assert instance._model_kwargs == new_instance._model_kwargs
        assert len(new_instance._constraints) == 1
        assert instance._constraints[0].to_dict() == new_instance._constraints[0].to_dict()
        assert len(new_instance._constraints_to_reverse) == 1
        assert instance._constraints_to_reverse[0].to_dict() == \
            new_instance._constraints_to_reverse[0].to_dict()

        for sdtype, transformer in instance._transformers_by_sdtype.items():
            assert repr(transformer) == repr(new_instance._transformers_by_sdtype[sdtype])

    def test_to_json_from_json(self):
        """Test that ``to_json`` and ``from_json`` methods are inverse to each other.

        Run ``from_json`` on a dict generated by ``to_json``, and ensure the result
        is the same as the original DataProcessor.

        Setup:
            - A DataProcessor with all its attributes set.
            - Use ``TemporaryDirectory`` to store the file.

        Input:
            - ``from_json`` and ``to_json`` take the same file name.

        Output:
            - The original DataProcessor instance.
        """
        # Setup
        metadata = SingleTableMetadata()
        metadata.add_column('col', sdtype='numerical')
        metadata.add_constraint('Positive', column_name='col')
        instance = DataProcessor(metadata=metadata)
        instance._constraints_to_reverse = [Positive('col')]

        # Run
        with TemporaryDirectory() as temp_dir:
            file_name = Path(temp_dir) / 'temp.json'
            instance.to_json(file_name)
            new_instance = instance.from_json(file_name)

        # Assert
        assert instance.metadata.to_dict() == new_instance.metadata.to_dict()
        assert instance._model_kwargs == new_instance._model_kwargs
        assert len(new_instance._constraints) == 1
        assert instance._constraints[0].to_dict() == new_instance._constraints[0].to_dict()
        assert len(new_instance._constraints_to_reverse) == 1
        assert instance._constraints_to_reverse[0].to_dict() == \
            new_instance._constraints_to_reverse[0].to_dict()

        for sdtype, transformer in instance._transformers_by_sdtype.items():
            assert repr(transformer) == repr(new_instance._transformers_by_sdtype[sdtype])

    def test_get_model_kwargs(self):
        """Test the ``get_model_kwargs`` method.

        The method should return a copy of the ``model_kwargs``.

        Input:
            - Model name.

        Output:
            - model key word args.
        """
        # Setup
        dp = DataProcessor(SingleTableMetadata())
        dp._model_kwargs = {'model': {'arg1': 10, 'arg2': True}}

        # Run
        model_kwargs = dp.get_model_kwargs('model')

        # Assert
        assert model_kwargs == {'arg1': 10, 'arg2': True}

    def test_set_model_kwargs(self):
        """Test the ``set_model_kwargs`` method.

        The method should set the ``model_kwargs`` for the provided model name.

        Input:
            - Model name.
            - Model key word args.

        Side effect:
            - ``_model_kwargs`` should be set.
        """
        # Setup
        dp = DataProcessor(SingleTableMetadata())

        # Run
        dp.set_model_kwargs('model', {'arg1': 10, 'arg2': True})

        # Assert
        assert dp._model_kwargs == {'model': {'arg1': 10, 'arg2': True}}

    def test_get_sdtypes(self):
        """Test that this returns a mapping of column names and its sdtypes.

        This test ensures that a dictionary is returned with column name as key and
        ``sdtype`` as value. When ``primary_keys`` is ``False`` this should not be included.
        """
        # Setup
        metadata = SingleTableMetadata()
        metadata.add_column('col1', sdtype='categorical')
        metadata.add_column('col2', sdtype='numerical')
        metadata.add_column('col3', sdtype='numerical', computer_representation='Int8')
        metadata.set_primary_key('col2')
        dp = DataProcessor(metadata)

        # Run
        sdtypes = dp.get_sdtypes()

        # Assert
        assert sdtypes == {
            'col1': 'categorical',
            'col3': 'numerical'
        }

    def test_get_sdtypes_with_primary_keys(self):
        """Test that this returns a mapping of column names and it's sdtypes.

        This test ensures that a dictionary is returned with column name as key and
        ``sdtype`` as value. When ``primary_keys`` is ``True`` this should be included.
        """
        # Setup
        metadata = SingleTableMetadata()
        metadata.add_column('col1', sdtype='categorical')
        metadata.add_column('col2', sdtype='numerical')
        metadata.add_column('col3', sdtype='numerical', computer_representation='Int8')
        metadata.set_primary_key('col2')
        dp = DataProcessor(metadata)

        # Run
        sdtypes = dp.get_sdtypes(primary_keys=True)

        # Assert
        assert sdtypes == {
            'col1': 'categorical',
            'col2': 'numerical',
            'col3': 'numerical'
        }

    def test__fit_transform_constraints(self):
        """Test the ``_fit_transform_constraints`` method.

        The method should loop through all the constraints, fit them,
        and then call ``transform`` for all of them.

        Setup:
            - Set the ``_constraints`` to be a list of mocked constraints.

        Input:
            - A ``pandas.DataFrame``.

        Output:
            - Same ``pandas.DataFrame``.

        Side effect:
            - Each constraint should be fit and transform the data.
        """
        # Setup
        data = pd.DataFrame({'a': [1, 2, 3]})
        transformed_data = pd.DataFrame({'a': [4, 5, 6]})
        dp = DataProcessor(SingleTableMetadata())
        constraint1 = Mock()
        constraint2 = Mock()
        constraint1.transform.return_value = transformed_data
        constraint2.transform.return_value = data
        dp._constraints = [constraint1, constraint2]

        # Run
        constrained_data = dp._fit_transform_constraints(data)

        # Assert
        constraint1.fit.assert_called_once_with(data)
        constraint2.fit.assert_called_once_with(data)
        constraint1.transform.assert_called_once_with(data)
        constraint2.transform.assert_called_once_with(transformed_data)
        pd.testing.assert_frame_equal(constrained_data, data)

    def test__fit_transform_constraints_fit_errors(self):
        """Test the ``_fit_transform_constraints`` method when constraints error on fit.

        The method should loop through all the constraints and try to fit them. If
        any errors are raised, they should be caught and surfaced together.

        Setup:
            - Set the ``_constraints`` to be a list of mocked constraints.
            - Set constraint mocks to raise Exceptions when calling fit.

        Input:
            - A ``pandas.DataFrame``.

        Side effect:
            - A ``AggregateConstraintsError`` error should be raised.
        """
        # Setup
        data = pd.DataFrame({'a': [1, 2, 3]})
        dp = DataProcessor(SingleTableMetadata())
        constraint1 = Mock()
        constraint2 = Mock()
        constraint1.fit.side_effect = Exception('error 1')
        constraint2.fit.side_effect = Exception('error 2')
        dp._constraints = [constraint1, constraint2]

        # Run / Assert
        error_message = re.escape('\nerror 1\n\nerror 2')
        with pytest.raises(AggregateConstraintsError, match=error_message):
            dp._fit_transform_constraints(data)

    def test__fit_transform_constraints_transform_errors(self):
        """Test the ``_fit_transform_constraints`` method when constraints error on transform.

        The method should loop through all the constraints and try to fit them. Then it
        should loop through again and try to transform. If any errors are raised, they should be
        caught and surfaced together.

        Setup:
            - Set the ``_constraints`` to be a list of mocked constraints.
            - Set constraint mocks to raise Exceptions when calling transform.

        Input:
            - A ``pandas.DataFrame``.

        Side effect:
            - A ``AggregateConstraintsError`` error should be raised.
        """
        # Setup
        data = pd.DataFrame({'a': [1, 2, 3]})
        dp = DataProcessor(SingleTableMetadata())
        constraint1 = Mock()
        constraint2 = Mock()
        constraint1.transform.side_effect = Exception('error 1')
        constraint2.transform.side_effect = Exception('error 2')
        dp._constraints = [constraint1, constraint2]

        # Run / Assert
        error_message = re.escape('\nerror 1\n\nerror 2')
        with pytest.raises(AggregateConstraintsError, match=error_message):
            dp._fit_transform_constraints(data)

        constraint1.fit.assert_called_once_with(data)
        constraint2.fit.assert_called_once_with(data)

    @patch('sdv.data_processing.data_processor.LOGGER')
    def test__fit_transform_constraints_missing_columns_error(self, log_mock):
        """Test the ``_fit_transform_constraints`` method when transform raises a errors.

        The method should loop through all the constraints and try to fit them. Then it
        should loop through again and try to transform. If a ``MissingConstraintColumnError`` or
        ``FunctionError`` is raised, a warning should be raised and reject sampling should be used.

        Setup:
            - Set the ``_constraints`` to be a list of mocked constraints.
            - Set constraint mocks to raise ``MissingConstraintColumnError`` and ``FunctionError``
            when calling transform.
            - Mock warnings module.

        Input:
            - A ``pandas.DataFrame``.

        Side effect:
            - ``MissingConstraintColumnError`` and ``FunctionError`` warning messages.
        """
        # Setup
        data = pd.DataFrame({'a': [1, 2, 3]})
        dp = DataProcessor(SingleTableMetadata())
        constraint1 = Mock()
        constraint2 = Mock()
        constraint3 = Mock()
        constraint1.transform.return_value = data
        constraint2.transform.side_effect = MissingConstraintColumnError(['column'])
        constraint3.transform.side_effect = FunctionError()
        dp._constraints = [constraint1, constraint2, constraint3]

        # Run
        dp._fit_transform_constraints(data)

        # Assert
        constraint1.fit.assert_called_once_with(data)
        constraint2.fit.assert_called_once_with(data)
        constraint3.fit.assert_called_once_with(data)
        assert log_mock.info.call_count == 2
        message1 = (
            "Mock cannot be transformed because columns: ['column'] were not found. Using the "
            'reject sampling approach instead.'
        )
        message2 = 'Error transforming Mock. Using the reject sampling approach instead.'
        log_mock.info.assert_has_calls([call(message1), call(message2)])

    def test__update_transformers_by_sdtypes(self):
        """Test that we update the ``_transformers_by_sdtype`` of the current instance."""
        # Setup
        instance = Mock()
        instance._transformers_by_sdtype = {
            'categorical': 'labelencoder',
            'numerical': 'float',
            'boolean': None
        }

        # Run
        DataProcessor._update_transformers_by_sdtypes(instance, 'categorical', None)

        # Assert
        assert instance._transformers_by_sdtype == {
            'categorical': None,
            'numerical': 'float',
            'boolean': None
        }

    @patch('sdv.data_processing.data_processor.rdt')
    def test_create_primary_key_transformer_regex_generator(self, mock_rdt):
        """Test the ``create_primary_key_transformer`` method.

        Test that when given an ``sdtype`` and ``column_metadata`` that contains ``regex_format``
        this creates and returns an instance of ``RegexGenerator``.

        Input:
            - String representing an ``sdtype``.
            - Dictionary with ``column_metadata`` that contains ``sdtype`` and ``regex_format``.

        Mock:
            - Mock ``rdt``.

        Output:
            - The return value of ``rdt.transformers.RegexGenerator``.
        """
        # Setup
        sdtype = 'text'
        column_metadata = {
            'sdtype': 'text',
            'regex_format': 'ID_00',
        }

        # Run
        output = DataProcessor.create_primary_key_transformer(Mock(), sdtype, column_metadata)

        # Assert
        assert output == mock_rdt.transformers.RegexGenerator.return_value
        mock_rdt.transformers.RegexGenerator.assert_called_once_with(
            regex_format='ID_00',
            enforce_uniqueness=True
        )

    def test_create_primary_key_transformer_anonymized_faker(self):
        """Test the ``create_primary_key_transformer`` method.

        Test that when given an ``sdtype`` and ``column_metadata`` that does not contain a
        ``regex_format`` this calls ``create_anonymized_transformer`` with ``enforce_uniqueness``
        set to ``True``.

        Input:
            - String representing an ``sdtype``.
            - Dictionary with ``column_metadata`` that contains ``sdtype``.

        Mock:
            - Mock the ``create_anonymized_transformer``.

        Output:
            - The return value of ``create_anonymized_transformer``.
        """
        # Setup
        sdtype = 'ssn'
        column_metadata = {
            'sdtype': 'ssn',
        }
        instance = Mock()

        # Run
        output = DataProcessor.create_primary_key_transformer(instance, sdtype, column_metadata)

        # Assert
        assert output == instance.create_anonymized_transformer.return_value
        instance.create_anonymized_transformer.assert_called_once_with(
            'ssn',
            {'sdtype': 'ssn', 'enforce_uniqueness': True}
        )

    @patch('sdv.data_processing.data_processor.get_anonymized_transformer')
    def test_create_anonymized_transformer(self, mock_get_anonymized_transformer):
        """Test the ``create_anonymized_transformer`` method.

        Test that when given an ``sdtype`` and ``column_metadata`` this calls the
        ``get_anonymized_transformer`` with filtering the ``pii`` and ``sdtype`` keyword args.

        Input:
            - String representing an ``sdtype``.
            - Dictionary with ``column_metadata`` that contains ``sdtype`` and ``pii``.

        Mock:
            - Mock the ``get_anonymized_transformer``.

        Output:
            - The return value of ``get_anonymized_transformer``.
        """
        # Setup
        sdtype = 'email'
        column_metadata = {
            'sdtype': 'email',
            'pii': True,
            'domain': 'gmail.com'
        }

        # Run
        output = DataProcessor.create_anonymized_transformer(sdtype, column_metadata)

        # Assert
        assert output == mock_get_anonymized_transformer.return_value
        mock_get_anonymized_transformer.assert_called_once_with('email', {'domain': 'gmail.com'})

    def test__create_config(self):
        """Test the ``_create_config`` method.

        The method should loop through the columns in the metadata and set the transformer
        for each column based on the sdtype. It should then loop through the columns in the
        ``columns_created_by_constraints`` list and either set them to use a ``FloatFormatter``
        or other transformer depending on their sdtype.

        Setup:
            - Create data with different column types.
            - Mock the metadata's columns.
        Input:
            - Data with columns both in the metadata and not.
            - columns_created_by_constraints as a list of the column names not in the metadata.

        Output:
            - The expected ``HyperTransformer`` config.
        """
        # Setup
        data = pd.DataFrame({
            'int': [1, 2, 3],
            'float': [1., 2., 3.],
            'bool': [True, False, True],
            'categorical': ['a', 'b', 'c'],
            'created_int': [4, 5, 6],
            'created_float': [4., 5., 6.],
            'created_bool': [False, True, False],
            'created_categorical': ['d', 'e', 'f'],
            'email': ['a@aol.com', 'b@gmail.com', 'c@gmx.com'],
            'id': ['ID_001', 'ID_002', 'ID_003']
        })
        dp = DataProcessor(SingleTableMetadata())
        dp.metadata = Mock()
        dp.create_anonymized_transformer = Mock()
        dp.create_primary_key_transformer = Mock()
        dp.create_anonymized_transformer.return_value = 'AnonymizedFaker'
        dp.create_primary_key_transformer.return_value = 'RegexGenerator'
        dp.metadata._primary_key = 'id'
        dp._primary_key = 'id'
        dp.metadata._columns = {
            'int': {'sdtype': 'numerical'},
            'float': {'sdtype': 'numerical'},
            'bool': {'sdtype': 'boolean'},
            'categorical': {'sdtype': 'categorical'},
            'email': {'sdtype': 'email', 'pii': True},
            'id': {'sdtype': 'text', 'regex_format': 'ID_\\d{3}[0-9]'}
        }

        # Run
        created_columns = {'created_int', 'created_float', 'created_bool', 'created_categorical'}
        config = dp._create_config(data, created_columns)

        # Assert
        assert config['sdtypes'] == {
            'int': 'numerical',
            'float': 'numerical',
            'bool': 'boolean',
            'categorical': 'categorical',
            'created_int': 'numerical',
            'created_float': 'numerical',
            'created_bool': 'boolean',
            'created_categorical': 'categorical',
            'email': 'pii',
            'id': 'text',
        }
        int_transformer = config['transformers']['created_int']
        assert isinstance(int_transformer, FloatFormatter)
        assert int_transformer.missing_value_replacement == 'mean'
        assert int_transformer.model_missing_values is True
        float_transformer = config['transformers']['created_float']
        assert isinstance(float_transformer, FloatFormatter)
        assert float_transformer.missing_value_replacement == 'mean'
        assert float_transformer.model_missing_values is True
        assert isinstance(config['transformers']['bool'], LabelEncoder)
        assert isinstance(config['transformers']['created_bool'], LabelEncoder)
        assert isinstance(config['transformers']['categorical'], LabelEncoder)
        assert isinstance(config['transformers']['created_categorical'], LabelEncoder)
        assert isinstance(config['transformers']['int'], FloatFormatter)
        assert isinstance(config['transformers']['float'], FloatFormatter)
        anonymized_transformer = config['transformers']['email']
        primary_key_transformer = config['transformers']['id']
        assert anonymized_transformer == 'AnonymizedFaker'
        assert primary_key_transformer == 'RegexGenerator'
        assert dp._anonymized_columns == ['email']
        dp.create_anonymized_transformer.assert_called_once_with(
            'email', {'sdtype': 'email', 'pii': True})
        dp.create_primary_key_transformer.assert_called_once_with(
            'text', {'sdtype': 'text', 'regex_format': 'ID_\\d{3}[0-9]'})

        assert dp._primary_key == 'id'

    def test_update_transformers_not_fitted(self):
        """Test when ``self._hyper_transformer`` is ``None`` raises a ``NotFittedError``."""
        # Setup
        dp = DataProcessor(SingleTableMetadata())

        # Run and Assert
        error_msg = (
            'The DataProcessor must be prepared for fitting before the transformers can be '
            'updated.'
        )
        with pytest.raises(NotFittedError, match=error_msg):
            dp.update_transformers({'column': None})

    @patch('sdv.data_processing.data_processor.rdt.HyperTransformer')
    def test__fit_hyper_transformer(self, ht_mock):
        """Test the ``_fit_hyper_transformer`` method.

        The method should create a ``HyperTransformer``, create a config from the data and
        set the ``HyperTransformer's`` config to be what was created. Then it should fit the
        ``HyperTransformer`` on the data.

        Setup:
            - Patch the ``HyperTransformer``.
            - Mock the ``_create_config`` method.

        Input:
            - A dataframe.

        Side effects:
            - ``HyperTransformer`` should fit the data.
        """
        # Setup
        dp = DataProcessor(SingleTableMetadata())
        ht_mock.return_value._fitted = False
        data = pd.DataFrame({'a': [1, 2, 3]})

        # Run
        dp._fit_hyper_transformer(data)

        # Assert
        ht_mock.return_value.fit.assert_called_once_with(data)

    @patch('sdv.data_processing.data_processor.rdt.HyperTransformer')
    def test__fit_hyper_transformer_empty_data(self, ht_mock):
        """Test the ``_fit_hyper_transformer`` method.

        If the data is empty, the ``HyperTransformer`` should not call fit.

        Setup:
            - Patch the ``HyperTransformer``.
            - Mock the ``_create_config`` method.

        Input:
            - An empty dataframe.

        Side effects:
            - ``HyperTransformer`` should not fit the data.
        """
        # Setup
        dp = DataProcessor(SingleTableMetadata())
        ht_mock.return_value._fitted = False
        ht_mock.return_value.field_transformers = {}
        data = pd.DataFrame()

        # Run
        dp._fit_hyper_transformer(data)

        # Assert
        ht_mock.return_value.fit.assert_not_called()

    @patch('sdv.data_processing.data_processor.rdt.HyperTransformer')
    def test__fit_hyper_transformer_hyper_transformer_is_fitted(self, ht_mock):
        """Test when ``self._hyper_transformer`` is not ``None``.

        This should not re-fit or re-create the ``self._hyper_transformer``.
        """
        # Setup
        dp = DataProcessor(SingleTableMetadata())
        dp._hyper_transformer = Mock()
        dp._hyper_transformer.field_transformers = {'name': 'categorical'}
        dp._hyper_transformer._fitted = True
        dp._create_config = Mock()
        data = pd.DataFrame({'name': ['John Doe']})

        # Run
        dp._fit_hyper_transformer(data)

        # Assert
        ht_mock.return_value.set_config.assert_not_called()
        ht_mock.return_value.fit.assert_not_called()
        dp._create_config.assert_not_called()

    @patch('sdv.data_processing.numerical_formatter.NumericalFormatter.learn_format')
    def test__fit_numerical_formatters(self, learn_format_mock):
        """Test the ``_fit_numerical_formatters`` method.

        Runs the methods through three columns: a non-numerical column, which should
        be skipped by the method, and two numerical ones (with different values for
        ``computer_representation``), which should create and learn a ``NumericalFormatter``.

        Setup:
            - ``SingleTableMetadata`` describing the three columns.
            - A mock of ``NumericalFormatter.learn_format``.
        """
        # Setup
        data = pd.DataFrame({'col1': ['abc', 'def'], 'col2': [1, 2], 'col3': [3, 4]})
        metadata = SingleTableMetadata()
        metadata.add_column('col1', sdtype='categorical')
        metadata.add_column('col2', sdtype='numerical')
        metadata.add_column('col3', sdtype='numerical', computer_representation='Int8')
        dp = DataProcessor(metadata, learn_rounding_scheme=False, enforce_min_max_values=False)

        # Run
        dp._fit_numerical_formatters(data)

        # Assert
        assert list(dp.formatters.keys()) == ['col2', 'col3']

        assert isinstance(dp.formatters['col2'], NumericalFormatter)
        assert dp.formatters['col2'].learn_rounding_scheme is False
        assert dp.formatters['col2'].enforce_min_max_values is False
        assert dp.formatters['col2'].computer_representation == 'Float'

        assert isinstance(dp.formatters['col3'], NumericalFormatter)
        assert dp.formatters['col3'].learn_rounding_scheme is False
        assert dp.formatters['col3'].enforce_min_max_values is False
        assert dp.formatters['col3'].computer_representation == 'Int8'

        learn_format_mock.assert_has_calls([call(data['col2']), call(data['col3'])])

    @patch('sdv.data_processing.data_processor.LOGGER')
    def test_prepare_for_fitting(self, log_mock):
        """Test the steps before fitting.

        Test that ``dtypes``, numerical formatters and constraints are being fitted before
        creating the configuration for the ``rdt.HyperTransformer``.
        """
        # Setup
        data = pd.DataFrame({'a': [1, 2, 3]}, dtype=np.int64)
        transformed_data = pd.DataFrame({'a': [4, 5, 6], 'b': [1, 2, 3]})
        dp = Mock()
        dp.table_name = 'fake_table'
        dp._fit_transform_constraints.return_value = transformed_data
        dp._hyper_transformer.field_transformers = {}

        # Run
        DataProcessor.prepare_for_fitting(dp, data)

        # Assert
        pd.testing.assert_series_equal(dp._dtypes, pd.Series([np.int64], index=['a']))
        dp._fit_transform_constraints.assert_called_once_with(data)
        dp._fit_numerical_formatters.assert_called_once_with(data)
        fitting_call = call('Fitting table fake_table metadata')
        formatter_call = call('Fitting numerical formatters for table fake_table')
        constraint_call = call('Fitting constraints for table fake_table')
        setting_config_call = call(
            'Setting the configuration for the ``HyperTransformer`` for table fake_table')
        log_mock.info.assert_has_calls(
            [fitting_call, formatter_call, constraint_call, setting_config_call])

    @patch('sdv.data_processing.data_processor.LOGGER')
    def test_fit(self, log_mock):
        """Test the ``fit`` method.

        The ``fit`` method should store the dtypes, learn the formatters for each column,
        fit and transform the constraints and then fit the ``HyperTransformer``.

        Setup:
            - Mock the ``prepare_for_fitting`` method.

        Input:
            - A ``pandas.DataFrame``.

        Side effect:
            - The ``_fit_hyper_transformer`` should be called.
        """
        # Setup
        data = pd.DataFrame({'a': [1, 2, 3]}, dtype=np.int64)
        transformed_data = pd.DataFrame({'a': [4, 5, 6], 'b': [1, 2, 3]})
        dp = Mock()
        dp.table_name = 'fake_table'
        dp._transform_constraints.return_value = transformed_data

        # Run
        DataProcessor.fit(dp, data)

        # Assert
        dp.prepare_for_fitting.assert_called_once_with(data)
        dp._transform_constraints.assert_called_once_with(data)
        dp._fit_hyper_transformer.assert_called_once_with(transformed_data)
        log_mock.info.assert_called_once_with('Fitting HyperTransformer for table fake_table')

    @patch('sdv.data_processing.data_processor.LOGGER')
    def test_transform(self, log_mock):
        """Test the ``transform`` method.

        The method should call the ``_transform_constraints`` and
        ``HyperTransformer.transform_subset``.

        Input:
            - Table data.

        Side Effects:
            - Calls ``_transform_constraints``.
            - Calls ``HyperTransformer.transform_subset``.
            - Calls logger with right messages.
        """
        # Setup
        data = pd.DataFrame({
            'item 0': [0, 1, 2],
            'item 1': [True, True, False]
        }, index=[0, 1, 2])
        dp = DataProcessor(SingleTableMetadata(), table_name='table_name')
        dp._transform_constraints = Mock()
        dp._transform_constraints.return_value = data
        dp._hyper_transformer = Mock()
        dp.get_sdtypes = Mock()
        dp.get_sdtypes.return_value = {
            'item 0': 'numerical',
            'item 1': 'boolean'
        }
        dp._hyper_transformer.transform_subset.return_value = data
        dp.fitted = True

        # Run
        dp.transform(data)

        # Assert
        expected_data = pd.DataFrame({
            'item 0': [0, 1, 2],
            'item 1': [True, True, False]
        }, index=[0, 1, 2])
        constraint_mock_calls = dp._transform_constraints.mock_calls
        ht_mock_calls = dp._hyper_transformer.transform_subset.mock_calls
        constraint_data, is_condition = constraint_mock_calls[0][1]
        ht_data = ht_mock_calls[0][1][0]
        assert len(constraint_mock_calls) == 1
        assert is_condition is False
        pd.testing.assert_frame_equal(constraint_data, expected_data)
        assert len(ht_mock_calls) == 1
        pd.testing.assert_frame_equal(ht_data, expected_data)
        constraint_call = call('Transforming constraints for table table_name')
        transformer_call = call('Transforming table table_name')
        log_mock.debug.assert_has_calls([constraint_call, transformer_call])

    def test_generate_primary_keys(self):
        """Test the ``genereate_primary_keys``.

        Test that when calling this function this calls the ``instance._hyper_transformer``'s
        ``create_anonymized_columns`` method with the ``num_rows`` and the
        ``instance._primary_keys``.

        Setup:
            - Mock the instance of ``DataProcessor``.
            - Set some ``_primary_keys``.

        Input:
            - ``num_rows``

        Side Effects:
            - ``instance._hyper_transformer.create_anonymized_columns`` has been called with the
              input number and ``column_names`` same as the ``instance._primary_keys``.

        Output:
            - The output should be the return value of the
              ``instance._hyper_transformer.create_anonymized_columns``.
        """
        # Setup
        instance = Mock()
        instance._primary_key = 'a'
        instance._hyper_transformer.field_transformers = {
            'a': object()
        }
        instance._primary_key_generator = None

        # Run
        result = DataProcessor.generate_primary_keys(instance, 10)

        # Assert
        instance._hyper_transformer.create_anonymized_columns.assert_called_once_with(
            num_rows=10,
            column_names=['a'],
        )

        assert result == instance._hyper_transformer.create_anonymized_columns.return_value

    def test_generate_primary_keys_reset_primary_key(self):
        """Test that a new ``counter`` is created when ``reset_primary_key`` is ``True``."""
        # Setup
        instance = Mock()
        instance._primary_key = 'a'
        instance._hyper_transformer.field_transformers = {}
        counter = itertools.count(start=10)

        # Run
        result = DataProcessor.generate_primary_keys(instance, 10, reset_primary_key=True)

        # Assert
        expected_result = pd.DataFrame({
            'a': [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        })

        pd.testing.assert_frame_equal(result, expected_result)
        assert instance._primary_key_generator != counter

    @patch('sdv.data_processing.data_processor.LOGGER')
    def test_transform_primary_key(self, log_mock):
        """Test the ``transform`` method.

        The method should call the ``_transform_constraints`` and
        ``HyperTransformer.transform_subset``.

        Input:
            - Table data.

        Side Effects:
            - Calls ``_transform_constraints``.
            - Calls ``HyperTransformer.transform_subset``.
            - Calls logger with right messages.
        """
        # Setup
        data = pd.DataFrame({
            'id': ['a', 'b', 'c'],
            'item 0': [0, 1, 2],
            'item 1': [True, True, False],
        }, index=[0, 1, 2])
        dp = DataProcessor(SingleTableMetadata(), table_name='table_name')
        dp._transform_constraints = Mock()
        dp._transform_constraints.return_value = data
        dp._hyper_transformer = Mock()
        dp._hyper_transformer.transform_subset.return_value = data
        dp._hyper_transformer.field_transformers = {'id': object()}
        dp.get_sdtypes = Mock()
        dp.get_sdtypes.return_value = {
            'id': 'categorical',
            'item 0': 'numerical',
            'item 1': 'boolean'
        }

        dp.fitted = True
        dp._primary_key = 'id'

        primary_key_data = pd.DataFrame({'id': ['a', 'b', 'c']})
        dp._hyper_transformer.create_anonymized_columns.return_value = primary_key_data

        # Run
        transformed = dp.transform(data)

        # Assert
        expected_data = pd.DataFrame({
            'id': ['a', 'b', 'c'],
            'item 0': [0, 1, 2],
            'item 1': [True, True, False]
        }, index=[0, 1, 2])

        constraint_mock_calls = dp._transform_constraints.mock_calls
        ht_mock_calls = dp._hyper_transformer.transform_subset.mock_calls
        constraint_data, is_condition = constraint_mock_calls[0][1]
        assert len(constraint_mock_calls) == 1
        assert is_condition is False
        assert len(ht_mock_calls) == 1

        constraint_call = call('Transforming constraints for table table_name')
        transformer_call = call('Transforming table table_name')
        log_mock.debug.assert_has_calls([constraint_call, transformer_call])

        pd.testing.assert_frame_equal(constraint_data, data)
        pd.testing.assert_frame_equal(transformed, expected_data)

    def test_transform_not_fitted(self):
        """Test the ``transform`` method if the ``DataProcessor`` was not fitted.

        The method should raise a ``NotFittedError``.

        Setup:
            - Set ``fitted`` to False.

        Input:
            - Table data.

        Side Effects:
            - Raises ``NotFittedError``.
        """
        # Setup
        data = pd.DataFrame({
            'item 0': [0, 1, 2],
            'item 1': [True, True, False]
        }, index=[0, 1, 2])
        dp = DataProcessor(SingleTableMetadata(), table_name='table_name')

        # Run
        with pytest.raises(NotFittedError):
            dp.transform(data)

    def test_transform_hyper_transformer_errors(self):
        """Test the ``transform`` method when ``HyperTransformer`` errors.

        The method should catch the error raised by the ``HyperTransformer`` and return
        the data unchanged.

        Input:
            - Table data.

        Output:
            - Same data.
        """
        # Setup
        data = pd.DataFrame({
            'item 0': [0, 1, 2],
            'item 1': [True, True, False]
        }, index=[0, 1, 2])
        dp = DataProcessor(SingleTableMetadata(), table_name='table_name')
        dp._transform_constraints = Mock()
        dp._transform_constraints.return_value = data
        dp._hyper_transformer = Mock()
        dp._hyper_transformer.transform_subset.side_effect = Error()
        dp.get_sdtypes = Mock()
        dp.get_sdtypes.return_value = {
            'item 0': 'numerical',
            'item 1': 'boolean'
        }
        dp.fitted = True

        # Run
        transformed_data = dp.transform(data)

        # Assert
        expected_data = pd.DataFrame({
            'item 0': [0, 1, 2],
            'item 1': [True, True, False]
        }, index=[0, 1, 2])
        constraint_mock_calls = dp._transform_constraints.mock_calls
        constraint_data, is_condition = constraint_mock_calls[0][1]
        assert len(constraint_mock_calls) == 1
        assert is_condition is False
        pd.testing.assert_frame_equal(constraint_data, expected_data)
        pd.testing.assert_frame_equal(transformed_data, expected_data)

    def test__transform_constraints(self):
        """Test that ``_transform_constraints`` correctly transforms data based on constraints.

        The method is expected to loop through constraints and call each constraint's ``transform``
        method on the data.

        Input:
            - Table data.
        Output:
            - Transformed data.
        """
        # Setup
        data = pd.DataFrame({
            'item 0': [0, 1, 2],
            'item 1': [3, 4, 5]
        }, index=[0, 1, 2])
        transformed_data = pd.DataFrame({
            'item 0': [0, 0.5, 1],
            'item 1': [6, 8, 10]
        }, index=[0, 1, 2])
        first_constraint_mock = Mock()
        second_constraint_mock = Mock()
        first_constraint_mock.transform.return_value = transformed_data
        second_constraint_mock.return_value = transformed_data
        dp = DataProcessor(SingleTableMetadata())
        dp._constraints = [first_constraint_mock, second_constraint_mock]

        # Run
        result = dp._transform_constraints(data)

        # Assert
        assert result.equals(transformed_data)
        first_constraint_mock.transform.assert_called_once_with(data)
        second_constraint_mock.transform.assert_called_once_with(transformed_data)
        assert dp._constraints_to_reverse == [
            first_constraint_mock,
            second_constraint_mock
        ]

    def test__transform_constraints_is_condition_drops_columns(self):
        """Test that ``_transform_constraints`` drops columns when necessary.

        The method is expected to drop columns associated with a constraint when its
        transform raises a ``MissingConstraintColumnError`` and the ``is_condition``
        flag is True.

        Input:
            - Table data.
            - ``is_condition`` set to True.
        Output:
            - Table with dropped columns.
        """
        # Setup
        data = pd.DataFrame({
            'item 0': [0, 1, 2],
            'item 1': [3, 4, 5]
        }, index=[0, 1, 2])
        constraint_mock = Mock()
        constraint_mock.transform.side_effect = MissingConstraintColumnError(missing_columns=[])
        constraint_mock.constraint_columns = ['item 0']
        dp = DataProcessor(SingleTableMetadata())
        dp._constraints = [constraint_mock]
        dp._constraints_to_reverse = [constraint_mock]

        # Run
        result = dp._transform_constraints(data, True)

        # Assert
        expected_result = pd.DataFrame({
            'item 1': [3, 4, 5]
        }, index=[0, 1, 2])
        assert result.equals(expected_result)
        assert dp._constraints_to_reverse == [constraint_mock]

    def test__transform_constraints_is_condition_false_returns_data(self):
        """Test that ``_transform_constraints`` returns data unchanged when necessary.

        The method is expected to return data unchanged when the constraint transform
        raises a ``MissingConstraintColumnError`` and the ``is_condition`` flag is False.

        Input:
            - Table data.
        Output:
            - Table with dropped columns.
        """
        # Setup
        data = pd.DataFrame({
            'item 0': [0, 1, 2],
            'item 1': [3, 4, 5]
        }, index=[0, 1, 2])
        constraint_mock = Mock()
        constraint_mock.transform.side_effect = MissingConstraintColumnError(missing_columns=[])
        constraint_mock.constraint_columns = ['item 0']
        dp = DataProcessor(SingleTableMetadata())
        dp._constraints = [constraint_mock]
        dp._constraints_to_reverse = [constraint_mock]

        # Run
        result = dp._transform_constraints(data, False)

        # Assert
        expected_result = pd.DataFrame({
            'item 0': [0, 1, 2],
            'item 1': [3, 4, 5]
        }, index=[0, 1, 2])
        assert result.equals(expected_result)
        assert dp._constraints_to_reverse == []

    def test_reverse_transform(self):
        """Test the ``reverse_transform`` method.

        This method should attempt to reverse transform all the columns using the
        ``HyperTransformer``. Then it should loop through the constraints and reverse
        transform all of them. Finally, it should cast all the columns to their original
        dtypes.

        Setup:
            - Mock the ``HyperTransformer``.
            - Set the ``_constraints_to_reverse`` to contain a mock constraint.
            - Set ``fitted`` to True.
            - Mock the ``_dtypes``.

        Input:
            - A dataframe.

        Output:
            - The reverse transformed data.
        """
        # Setup
        constraint_mock = Mock()
        dp = DataProcessor(SingleTableMetadata())
        dp._anonymized_columns = ['d']
        dp.fitted = True
        dp.metadata = Mock()
        dp.metadata._columns = {'a': None, 'b': None, 'c': None, 'd': None}
        data = pd.DataFrame({
            'a': [1, 2, 3],
            'b': [True, True, False],
            'c': ['d', 'e', 'f'],
        })
        dp._hyper_transformer = Mock()
        dp._hyper_transformer.create_anonymized_columns.return_value = pd.DataFrame({
            'd': ['a@gmail.com', 'b@gmail.com', 'c@gmail.com']
        })
        dp._constraints_to_reverse = [constraint_mock]
        dp._hyper_transformer.reverse_transform_subset.return_value = data
        dp._hyper_transformer._output_columns = ['a', 'b', 'c']
        dp._dtypes = pd.Series(
            [np.float64, np.bool_, np.object_, np.object_], index=['a', 'b', 'c', 'd'])
        constraint_mock.reverse_transform.return_value = data

        # Run
        reverse_transformed = dp.reverse_transform(data)

        # Assert
        input_data = pd.DataFrame({
            'a': [1, 2, 3],
            'b': [True, True, False],
            'c': ['d', 'e', 'f']
        })
        constraint_mock.reverse_transform.assert_called_once_with(data)
        data_from_call = dp._hyper_transformer.reverse_transform_subset.mock_calls[0][1][0]
        pd.testing.assert_frame_equal(input_data, data_from_call)
        dp._hyper_transformer.reverse_transform_subset.assert_called_once()
        expected_output = pd.DataFrame({
            'a': [1., 2., 3.],
            'b': [True, True, False],
            'c': ['d', 'e', 'f'],
            'd': ['a@gmail.com', 'b@gmail.com', 'c@gmail.com']
        })
        dp._hyper_transformer.create_anonymized_columns.assert_called_once_with(
            num_rows=3,
            column_names=['d']
        )
        pd.testing.assert_frame_equal(reverse_transformed, expected_output)

    @patch('sdv.data_processing.data_processor.LOGGER')
    def test_reverse_transform_hyper_transformer_errors(self, log_mock):
        """Test the ``reverse_transform`` method.

        A message should be logged if the ``HyperTransformer`` errors.

        Setup:
            - Patch the logger.
            - Mock the ``HyperTransformer``.
            - Set the ``_constraints_to_reverse`` to contain a mock constraint.
            - Set ``fitted`` to True.
            - Mock the ``_dtypes``.

        Input:
            - A dataframe.

        Output:
            - The reverse transformed data.
        """
        # Setup
        constraint_mock = Mock()
        dp = DataProcessor(SingleTableMetadata(), table_name='table_name')
        dp.fitted = True
        dp.metadata = Mock()
        dp.metadata._columns = {'a': None, 'b': None, 'c': None}
        data = pd.DataFrame({
            'a': [1, 2, 3],
            'b': [True, True, False],
            'c': ['d', 'e', 'f']
        })
        dp._hyper_transformer = Mock()
        dp._constraints_to_reverse = [constraint_mock]
        dp._hyper_transformer.reverse_transform_subset.side_effect = RDTNotFittedError
        dp._hyper_transformer._output_columns = ['a', 'b', 'c']
        dp._dtypes = pd.Series([np.float64, np.bool_, np.object_], index=['a', 'b', 'c'])
        constraint_mock.reverse_transform.return_value = data

        # Run
        reverse_transformed = dp.reverse_transform(data)

        # Assert
        input_data = pd.DataFrame({
            'a': [1, 2, 3],
            'b': [True, True, False],
            'c': ['d', 'e', 'f']
        })
        constraint_mock.reverse_transform.assert_called_once_with(data)
        data_from_call = dp._hyper_transformer.reverse_transform_subset.mock_calls[0][1][0]
        message = 'HyperTransformer has not been fitted for table table_name'
        log_mock.info.assert_called_with(message)
        pd.testing.assert_frame_equal(input_data, data_from_call)
        expected_output = pd.DataFrame({
            'a': [1., 2., 3.],
            'b': [True, True, False],
            'c': ['d', 'e', 'f']
        })
        pd.testing.assert_frame_equal(reverse_transformed, expected_output)

    def test_reverse_transform_not_fitted(self):
        """Test the ``reverse_transform`` method if the ``DataProcessor`` was not fitted.

        The method should raise a ``NotFittedError``.

        Setup:
            - Set ``fitted`` to False.

        Input:
            - Table data.

        Side Effects:
            - Raises ``NotFittedError``.
        """
        # Setup
        data = pd.DataFrame({
            'item 0': [0, 1, 2],
            'item 1': [True, True, False]
        }, index=[0, 1, 2])
        dp = DataProcessor(SingleTableMetadata(), table_name='table_name')

        # Run
        with pytest.raises(NotFittedError):
            dp.reverse_transform(data)

    def test_reverse_transform_integer_rounding(self):
        """Test the ``reverse_transform`` method correctly rounds.

        Expect the data to be rounded when the ``dtypes`` specifies
        the ``'dtype'`` as ``'integer'``.

        Input:
            - A dataframe.
        Output:
            - The input dictionary rounded.
        """
        # Setup
        data = pd.DataFrame({'bar': [0.2, 1.7, 2]})
        dp = DataProcessor(SingleTableMetadata())
        dp.fitted = True
        dp._hyper_transformer = Mock()
        dp._hyper_transformer._output_columns = []
        dp._hyper_transformer.reverse_transform_subset.return_value = data
        dp._constraints_to_reverse = []
        dp._dtypes = {'bar': 'int'}
        dp.metadata = Mock()
        dp.metadata._columns = {'bar': None}

        # Run
        output = dp.reverse_transform(data)

        # Assert
        expected_data = pd.DataFrame({'bar': [0, 2, 2]})
        pd.testing.assert_frame_equal(output, expected_data, check_dtype=False)

    @patch('sdv.data_processing.numerical_formatter.NumericalFormatter')
    @patch('sdv.data_processing.numerical_formatter.NumericalFormatter')
    def test_reverse_transform_numerical_formatter(self, formatter_mock1, formatter_mock2):
        """Test the ``reverse_transform`` correctly applies the ``NumericalFormatter``.

        Runs the method through three columns: a non-numerical column, which should
        be skipped by the method, and two numerical ones which should call the
        ``NumericalFormatter.format_data`` method with a column each and return them
        unchanged.

        Setup:
            - ``SingleTableMetadata`` describing the three columns.
            - Two mocks of ``NumericalFormatter``, one for each numerical column,
            with the appropriate return value for the ``format_data`` method.
            - ``formatters`` attribute should have a dict of the two numerical columns
            mapped to the two mocked ``NumericalFormatters``.
        """
        # Setup
        data = pd.DataFrame({'col1': [1, 2], 'col2': [3, 4], 'col3': ['abc', 'def']})
        metadata = SingleTableMetadata()
        metadata.add_column('col1', sdtype='numerical')
        metadata.add_column('col2', sdtype='numerical')
        metadata.add_column('col3', sdtype='categorical')

        dp = DataProcessor(metadata)
        dp.formatters = {'col1': formatter_mock1, 'col2': formatter_mock2}
        formatter_mock1.format_data.return_value = np.array([1, 2])
        formatter_mock2.format_data.return_value = np.array([3, 4])

        # Unrelated setup, required so the method doesn't crash
        dp._hyper_transformer = Mock()
        dp._hyper_transformer._output_columns = []
        dp._hyper_transformer.reverse_transform_subset.return_value = data
        dp._dtypes = {'col1': 'int', 'col2': 'int', 'col3': 'str'}
        dp.fitted = True

        # Run
        output = dp.reverse_transform(data)

        # Assert
        formatter_mock1.format_data.assert_called_once()
        np.testing.assert_array_equal(
            formatter_mock1.format_data.call_args[0][0], data['col1'].to_numpy())

        formatter_mock2.format_data.assert_called_once()
        np.testing.assert_array_equal(
            formatter_mock2.format_data.call_args[0][0], data['col2'].to_numpy())

        pd.testing.assert_frame_equal(output, data)