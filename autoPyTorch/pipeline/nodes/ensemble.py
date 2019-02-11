__author__ = "Max Dippel, Michael Burkart and Matthias Urban"
__version__ = "0.0.1"
__license__ = "BSD"

import os

from autoPyTorch.pipeline.base.pipeline_node import PipelineNode
from autoPyTorch.utils.config.config_option import ConfigOption
from autoPyTorch.pipeline.nodes.metric_selector import MetricSelector
from autoPyTorch.pipeline.nodes import OneHotEncoding
from autoPyTorch.utils.ensemble import build_ensemble, read_ensemble_prediction_file, predictions_for_ensemble, combine_predictions, combine_test_predictions, \
    ensemble_logger
from hpbandster.core.result import logged_results_to_HBS_result


class EnableComputePredictionsForEnsemble(PipelineNode):
    """Put this Node in the training pipeline after the metric selector node"""
    def fit(self, pipeline_config, additional_metrics, refit, loss_penalty):
        if refit or pipeline_config["ensemble_size"] == 0 or loss_penalty > 0:
            return dict()
        return {'additional_metrics': additional_metrics + [predictions_for_ensemble]}


class SavePredictionsForEnsemble(PipelineNode):
    """Put this Node in the training pipeline after the training node"""
    def fit(self, pipeline_config, loss, info, refit, loss_penalty):
        if refit or pipeline_config["ensemble_size"] == 0 or loss_penalty > 0:
            return {"loss": loss, "info": info}

        if "val_predictions_for_ensemble" in info:
            predictions = info["val_predictions_for_ensemble"]
            del info["val_predictions_for_ensemble"]
        else:
            raise ValueError("You need to specify some kind of validation for ensemble building")
        del info["train_predictions_for_ensemble"]

        combinator = {
            "combinator": combine_predictions,
            "data": predictions
        }

        if not "test_predictions_for_ensemble" in info:
            return {"loss": loss, "info": info, "predictions_for_ensemble": combinator}
        
        test_combinator = {
            "combinator": combine_test_predictions,
            "data": info["test_predictions_for_ensemble"]
        }
        del info["test_predictions_for_ensemble"]
        return {"loss": loss, "info": info, "predictions_for_ensemble": combinator, "test_predictions_for_ensemble": test_combinator} 

    def predict(self, Y):
        return {"Y": Y}


class BuildEnsemble(PipelineNode):
    """Put this node after the optimization algorithm node"""
    def fit(self, pipeline_config, final_metric_score, optimized_hyperparameter_config, budget, refit=None):
        if refit or pipeline_config["ensemble_size"] == 0 or pipeline_config["task_id"] not in [-1, 1]:
            return {"final_metric_score": final_metric_score, "optimized_hyperparameter_config": optimized_hyperparameter_config, "budget": budget}
        
        filename = os.path.join(pipeline_config["result_logger_dir"], 'predictions_for_ensemble.npy')
        train_metric = self.pipeline[MetricSelector.get_name()].metrics[pipeline_config["train_metric"]]
        y_transform = self.pipeline[OneHotEncoding.get_name()].complete_y_tranformation
        result = logged_results_to_HBS_result(pipeline_config["result_logger_dir"])

        all_predictions, labels, model_identifiers, _ = read_ensemble_prediction_file(filename=filename, y_transform=y_transform)
        ensemble_selection, ensemble_configs = build_ensemble(result=result,
            train_metric=train_metric, minimize=pipeline_config["minimize"], ensemble_size=pipeline_config["ensemble_size"],
            all_predictions=all_predictions, labels=labels, model_identifiers=model_identifiers,
            only_consider_n_best=pipeline_config["ensemble_only_consider_n_best"],
            sorted_initialization_n_best=pipeline_config["ensemble_sorted_initialization_n_best"])

        return {"final_metric_score": final_metric_score, "optimized_hyperparameter_config": optimized_hyperparameter_config, "budget": budget,
            "ensemble": ensemble_selection, "ensemble_final_metric_score": ensemble_selection.get_validation_performance(),
            "ensemble_configs": ensemble_configs
            }
    
    def predict(self, Y):
        return {"Y": Y}
    
    def get_pipeline_config_options(self):
        options = [
            ConfigOption("ensemble_size", default=3, type=int, info="Build a ensemble of well performing autonet configurations. 0 to disable."),
            ConfigOption("ensemble_only_consider_n_best", default=0, type=int, info="Only consider the n best models for ensemble building."),
            ConfigOption("ensemble_sorted_initialization_n_best", default=0, type=int, info="Initialize ensemble with n best models.")
        ]
        return options

class AddEnsembleLogger(PipelineNode):
    """Put this node in fromt of the optimization algorithm node"""
    def fit(self, pipeline_config, result_loggers, refit=False):
        if refit or pipeline_config["ensemble_size"] == 0:
            return dict()
        result_loggers = [ensemble_logger(directory=pipeline_config["result_logger_dir"], overwrite=True)] + result_loggers
        return {"result_loggers": result_loggers}