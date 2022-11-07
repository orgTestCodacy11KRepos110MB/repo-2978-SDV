import re
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from sdv.data_processing.data_processor import DataProcessor
from sdv.metadata.single_table import SingleTableMetadata
from sdv.sequential.par import PARSynthesizer
from sdv.single_table.copulas import GaussianCopulaSynthesizer


class TestPARSynthesizer:

    def get_metadata(self, add_sequence_key=True):
        metadata = SingleTableMetadata()
        metadata.add_column('time', sdtype='datetime')
        metadata.add_column('gender', sdtype='categorical')
        metadata.add_column('name', sdtype='text')
        metadata.add_column('measurement', sdtype='numerical')
        if add_sequence_key:
            metadata.set_sequence_key('name')

        return metadata

    def get_data(self):
        data = pd.DataFrame({
            'time': [1, 2, 3],
            'gender': ['F', 'M', 'M'],
            'name': ['Jane', 'John', 'Doe'],
            'measurement': [55, 60, 65]
        })
        return data

    def test___init__(self):
        """Test that the parameters are set correctly.

        The parameters passed in the ``__init__`` should be set on the instance. Additionally,
        a context synthesizer should be created with the correct metadata and parameters.
        """
        # Setup
        metadata = self.get_metadata()

        # Run
        synthesizer = PARSynthesizer(
            metadata=metadata,
            enforce_min_max_values=True,
            enforce_rounding=True,
            context_columns=['gender'],
            segment_size=10,
            epochs=10,
            sample_size=5,
            cuda=False,
            verbose=False
        )

        # Assert
        assert synthesizer.context_columns == ['gender']
        assert synthesizer._sequence_key == ['name']
        assert synthesizer.enforce_min_max_values is True
        assert synthesizer.enforce_rounding is True
        assert synthesizer.segment_size == 10
        assert synthesizer._model_kwargs == {
            'epochs': 10,
            'sample_size': 5,
            'cuda': False,
            'verbose': False
        }
        assert isinstance(synthesizer._data_processor, DataProcessor)
        assert synthesizer._data_processor.metadata == metadata
        assert isinstance(synthesizer._context_synthesizer, GaussianCopulaSynthesizer)
        assert synthesizer._context_synthesizer.metadata._columns == {
            'gender': {'sdtype': 'categorical'},
            'name': {'sdtype': 'text'}
        }

    def test_get_parameters(self):
        """Test that it returns every ``init`` parameter without the ``metadata``."""
        # Setup
        metadata = SingleTableMetadata()
        instance = PARSynthesizer(
            metadata=metadata,
            enforce_min_max_values=True,
            enforce_rounding=True,
            context_columns=None,
            segment_size=10,
            epochs=10,
            sample_size=5,
            cuda=False,
            verbose=False
        )

        # Run
        parameters = instance.get_parameters()

        # Assert
        assert 'metadata' not in parameters
        assert parameters == {
            'enforce_min_max_values': True,
            'enforce_rounding': True,
            'context_columns': None,
            'segment_size': 10,
            'epochs': 10,
            'sample_size': 5,
            'cuda': False,
            'verbose': False
        }

    def test_get_metadata(self):
        """Test that it returns the ``metadata`` object."""
        # Setup
        metadata = SingleTableMetadata()
        instance = PARSynthesizer(
            metadata=metadata,
            enforce_min_max_values=True,
            enforce_rounding=True,
            context_columns=None,
            segment_size=10,
            epochs=10,
            sample_size=5,
            cuda=False,
            verbose=False
        )

        # Run
        result = instance.get_metadata()

        # Assert
        assert result == metadata

    @patch('sdv.sequential.par.BaseSynthesizer.preprocess')
    def test_preprocess_transformers_not_assigned(self, base_preprocess_mock):
        """Test that the method auto assigns the transformers if not already done.

        If the transformers in the ``DataProcessor`` haven't been assigned, then this method
        should do it so that it can overwrite the transformers for all the sequence key columns.
        """
        # Setup
        metadata = self.get_metadata()
        par = PARSynthesizer(
            metadata=metadata
        )
        par.auto_assign_transformers = Mock()
        par.update_transformers = Mock()
        data = self.get_data()

        # Run
        par.preprocess(data)

        # Assert
        expected_transformers = {'name': None}
        par.auto_assign_transformers.assert_called_once_with(data)
        par.update_transformers.assert_called_once_with(expected_transformers)
        base_preprocess_mock.assert_called_once_with(data)

    @patch('sdv.sequential.par.BaseSynthesizer.preprocess')
    def test_preprocess(self, base_preprocess_mock):
        """Test that the method does not auto assign the transformers if it's already been done.

        To test this, we set the hyper transformer to have its ``field_transformers`` set.
        """
        # Setup
        metadata = self.get_metadata()
        par = PARSynthesizer(
            metadata=metadata
        )
        par.auto_assign_transformers = Mock()
        par.update_transformers = Mock()
        par._data_processor._hyper_transformer.field_transformers = {
            'time': None,
            'gender': None,
            'name': None,
            'measurement': None
        }
        data = self.get_data()

        # Run
        par.preprocess(data)

        # Assert
        expected_transformers = {'name': None}
        par.auto_assign_transformers.assert_not_called()
        par.update_transformers.assert_called_once_with(expected_transformers)
        base_preprocess_mock.assert_called_once_with(data)

    def test__fit_context_model_with_context_columns(self):
        """Test that the method fits a synthesizer to the context columns.

        If there are context columns, the method should create a new DataFrame that groups
        the data by the sequence_key and only contains the context columns. Then a synthesizer
        should be fit to this new data.
        """
        # Setup
        metadata = self.get_metadata()
        data = self.get_data()
        par = PARSynthesizer(metadata, context_columns=['gender'])
        par._context_synthesizer = Mock()

        # Run
        par._fit_context_model(data)

        # Assert
        fitted_data = par._context_synthesizer.fit.mock_calls[0][1][0]
        expected_fitted_data = pd.DataFrame({
            'name': ['Doe', 'Jane', 'John'],
            'gender': ['M', 'F', 'M']
        })
        pd.testing.assert_frame_equal(fitted_data.sort_values(by='name'), expected_fitted_data)

    @patch('sdv.sequential.par.uuid')
    def test__fit_context_model_without_context_columns(self, uuid_mock):
        """Test that the method fits a synthesizer to a constant column.

        If there are no context columns, the method should create a constant column and
        group that by the sequence key. Then a synthesizer should be fit to this new data.
        """
        # Setup
        metadata = self.get_metadata()
        data = self.get_data()
        par = PARSynthesizer(metadata)
        par._context_synthesizer = Mock()
        uuid_mock.uuid4.return_value = 'abc'

        # Run
        par._fit_context_model(data)

        # Assert
        fitted_data = par._context_synthesizer.fit.mock_calls[0][1][0]
        expected_fitted_data = pd.DataFrame({
            'name': ['Doe', 'Jane', 'John'],
            'abc': [0, 0, 0]
        })
        pd.testing.assert_frame_equal(fitted_data.sort_values(by='name'), expected_fitted_data)

    @patch('sdv.sequential.par.PARModel')
    @patch('sdv.sequential.par.assemble_sequences')
    def test__fit_sequence_columns(self, assemble_sequences_mock, model_mock):
        """Test that the method assembles sequences properly and fits the ``PARModel`` to them.

        The method should use the ``assemble_sequences`` method to create a list of sequences
        that the model can fit to. It also needs to extract the data types for the context
        and non-context columns.
        """
        # Setup
        data = self.get_data()
        metadata = self.get_metadata()
        par = PARSynthesizer(
            metadata=metadata,
            context_columns=['gender']
        )
        sequences = [
            {'context': np.array(['M'], dtype=object), 'data': [[3], [65]]},
            {'context': np.array(['F'], dtype=object), 'data': [[1], [55]]},
            {'context': np.array(['M'], dtype=object), 'data': [[2], [60]]}
        ]
        assemble_sequences_mock.return_value = sequences

        # Run
        par._fit_sequence_columns(data)

        # Assert
        assemble_sequences_mock.assert_called_once_with(
            data,
            ['name'],
            ['gender'],
            None,
            None,
            drop_sequence_index=False
        )
        model_mock.assert_called_once_with(epochs=128, sample_size=1, cuda=True, verbose=False)
        model_mock.return_value.fit_sequences.assert_called_once_with(
            sequences,
            ['categorical'],
            ['continuous', 'continuous']
        )

    @patch('sdv.sequential.par.PARModel')
    @patch('sdv.sequential.par.assemble_sequences')
    def test__fit_sequence_columns_with_sequence_index(self, assemble_sequences_mock, model_mock):
        """Test the method when a sequence_index is present.

        If there is a sequence_index, the method should transform it by taking the sequence index
        and turning into to columns: one that is a list of diffs between each consecutive value in
        the sequence index, and another that is the starting value for the sequence index.
        """
        # Setup
        data = pd.DataFrame({
            'time': [1, 2, 3, 5, 8],
            'gender': ['F', 'F', 'M', 'M', 'M'],
            'name': ['Jane', 'Jane', 'John', 'John', 'John'],
            'measurement': [55, 60, 65, 65, 70]
        })
        metadata = self.get_metadata()
        metadata.set_sequence_index('time')
        par = PARSynthesizer(
            metadata=metadata,
            context_columns=['gender']
        )
        sequences = [
            {'context': np.array(['F'], dtype=object), 'data': [[1, 2], [55, 60]]},
            {'context': np.array(['M'], dtype=object), 'data': [[3, 5, 8], [65, 65, 70]]},
        ]
        assemble_sequences_mock.return_value = sequences

        # Run
        par._fit_sequence_columns(data)

        # Assert
        assemble_sequences_mock.assert_called_once_with(
            data,
            ['name'],
            ['gender'],
            None,
            'time',
            drop_sequence_index=False
        )
        expected_sequences = [
            {'context': np.array(['F'], dtype=object), 'data': [[1, 1], [55, 60], [1, 1]]},
            {
                'context': np.array(['M'], dtype=object),
                'data': [[2, 2, 3], [65, 65, 70], [3, 3, 3]]
            }
        ]
        model_mock.assert_called_once_with(epochs=128, sample_size=1, cuda=True, verbose=False)
        model_mock.return_value.fit_sequences.assert_called_once_with(
            expected_sequences,
            ['categorical'],
            ['continuous', 'continuous', 'continuous']
        )

    @patch('sdv.sequential.par.PARModel')
    @patch('sdv.sequential.par.assemble_sequences')
    def test__fit_sequence_columns_bad_dtype(self, assemble_sequences_mock, model_mock):
        """Test the method when a column has an unsupported dtype."""
        # Setup
        datetime = pd.Series(
            [pd.to_datetime('1/1/1999'), pd.to_datetime('1/2/1999'), '1/3/1999'],
            dtype='<M8[ns]')
        data = pd.DataFrame({
            'time': datetime,
            'gender': ['F', 'M', 'M'],
            'name': ['Jane', 'John', 'Doe'],
            'measurement': [55, 60, 65]
        })
        metadata = self.get_metadata()
        par = PARSynthesizer(
            metadata=metadata,
            context_columns=['gender']
        )

        # Run and Assert
        with pytest.raises(ValueError, match=re.escape('Unsupported dtype datetime64[ns]')):
            par._fit_sequence_columns(data)

    def test__fit_with_sequence_key(self):
        """Test that the method fits the context columns if there is a sequence key.

        When a sequence key is present, the context columns should be fitted before the rest of
        the columns.
        """
        # Setup
        metadata = self.get_metadata()
        par = PARSynthesizer(metadata=metadata)
        data = self.get_data()
        par._fit_context_model = Mock()
        par._fit_sequence_columns = Mock()

        # Run
        par._fit(data)

        # Assert
        par._fit_context_model.assert_called_once_with(data)
        par._fit_sequence_columns.assert_called_once_with(data)

    def test__fit_without_sequence_key(self):
        """Test that the method doesn't fit the context synthesizer if there are no sequence keys.

        If there are no sequence keys, then only the ``PARModel`` needs to be fit.
        """
        # Setup
        metadata = self.get_metadata(add_sequence_key=False)
        par = PARSynthesizer(metadata=metadata)
        data = self.get_data()
        par._fit_context_model = Mock()
        par._fit_sequence_columns = Mock()

        # Run
        par._fit(data)

        # Assert
        par._fit_context_model.assert_not_called()
        par._fit_sequence_columns.assert_called_once_with(data)