#!/usr/bin/python
# -*- coding:utf-8 -*-
'''
NN_Parser Neural Network Parser
@author: xichen ding
@date: 2017-03-01
'''

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals # compatible with python3 unicode coding

import sys, os
import tensorflow as tf
import numpy as np
import glob

# adding parser submodule to sys.path, compatible with py3 absolute_import
pkg_path = os.path.dirname(os.path.abspath(__file__)) # .../deepnlp/
sys.path.append(pkg_path)

from parse import parse_model as parse_model
from parse import reader as parse_reader
from parse import transition_system
from parse.transition_system import Configuration
from parse.reader import Sentence
from parse.reader import DependencyTree

from pos_tagger import ModelLoader as PosModelLoader

UNKNOWN = "*"

class ModelLoader(object):
    
    def __init__(self, lang, data_path, ckpt_path):
        self.lang = lang
        self.data_path = data_path
        self.ckpt_path = ckpt_path  # the path of the ckpt file, e.g. ./ckpt/zh/pos.ckpt
        print("NOTICE: Starting new Tensorflow session...")
        self.session = tf.Session()
        print("NOTICE: Initializing nn_parser class...")
        self.model = self._init_model(self.session, self.ckpt_path)

        # data utils for parsing: 
        vocab_dict_path = os.path.join(self.data_path, "vocab_dict")
        pos_dict_path = os.path.join(self.data_path, "pos_dict")
        label_dict_path = os.path.join(self.data_path, "label_dict")
        feature_tpl_path = os.path.join(self.data_path, "parse.template")

        self.vocab_dict = parse_reader._read_vocab(vocab_dict_path)
        self.pos_dict = parse_reader._read_vocab(pos_dict_path)
        self.label_dict = parse_reader._read_vocab(label_dict_path)
        self.feature_tpl = parse_reader._read_template(feature_tpl_path)
        self.arc_labels = transition_system.generate_arcs(self.label_dict)  # Arc Labels: <K,V>   (L(1), 1)

        self.rev_vocab_dict = parse_reader._reverse_map(self.vocab_dict)
        self.rev_pos_dict = parse_reader._reverse_map(self.pos_dict)
        self.rev_label_dict = parse_reader._reverse_map(self.label_dict)
        self.rev_arc_labels = parse_reader._reverse_map(self.arc_labels) 

        print ("NOTICE: vocab_dict size %d" % len(self.vocab_dict))
        print ("NOTICE: pos_dict size %d" % len(self.pos_dict))
        print ("NOTICE: label_dict size %d" % len(self.label_dict))
        print ("NOTICE: arc_labels size %d" % len(self.arc_labels))
        print ("NOTICE: feature templates size %d" % len(self.feature_tpl))
        
        # Load Default Pos Model for Input Pos Tags
        pos_data_path = os.path.join(pkg_path, "pos/data", lang) # POS vocabulary data path
        pos_ckpt_path = os.path.join(pkg_path, "pos/ckpt", lang, "pos.ckpt") # POS model checkpoint path
        self.pos_tagger_model = PosModelLoader(lang, pos_data_path, pos_ckpt_path)

    def predict(self, words, tags = None):
        ''' Main function to make prediction of a sentence with words and tags as input
            Args: 
                words: list of string
                tags: list of pos tags for input words, None means using default deepnlp Pos Tags
            Return: a DependencyTree obj,
                use print (tree) to see the detailed representation
                tree.get_head(k) return the head word index of kth word
                tree.get_label(k) return the dependency label of the kth word
        '''
        if (tags):
            dep_tree = self._predict(self.session, self.model, words, tags)
            return dep_tree
        else:
            tagging = self.pos_tagger_model.predict(words)
            tags = []
            for w, t in tagging:
                tags.append(t)
            print ("NOTICE: POS Tags: %s" % ",".join(tags))
            dep_tree = self._predict(self.session, self.model, words, tags)
            return dep_tree
    
    ## Initialize and Instance, Define Config Parameters
    def _init_model(self, session, ckpt_path):
        """Create Parser model and initialize with random or load parameters in session."""
        config = parse_model.get_config(self.lang)
        
        with tf.variable_scope("parse_var_scope"):
            model = parse_model.NNParser(config=config)

        print ("DEBUG: Checkpoint Path is %s" % self.ckpt_path)
        if os.path.exists(self.ckpt_path):
            model.saver.restore(session, tf.train.latest_checkpoint(self.ckpt_path))
            print("NOTICE: Loading model parameters from %s" % ckpt_path)
        else:
            print("DEBUG: Model not found, created with fresh parameters.")
            session.run(tf.global_variables_initializer())
        #if len(glob.glob(ckpt_path + '.data*')) > 0: # file exist with pattern: 'pos.ckpt.data*'
        #    print("Loading model parameters from %s" % ckpt_path)
        #    all_vars = tf.global_variables()
        #    model_vars = [k for k in all_vars if k.name.startswith("parse_var_scope")]
        #    tf.train.Saver(model_vars).restore(session, ckpt_path)
        #else:
        #    print("Model not found, created with fresh parameters.")
        #    session.run(tf.global_variables_initializer())
        return model
    
    def _predict(self, session, model, words, tags):
        ''' Define prediction function of Parsing
        Args:  
            Words : list of Words tokens; 
            Tags: list of POS tags
        Return: 
            Object of DependencyTree, defined in reader
            list: label_names, label name of each input word
        '''
        if (len(words) != len(tags)):
            print ("words list and tags list length is different")
            return
        if (len(words)==0 or len(tags) == 0):
            print ("DEBUG: words or tags list is empty")
            return
        # convert words and tags to Sentence object, sentence save the word_id and tag_id; UNKNOWN is '*
        sent = Sentence() 
        for w, t in zip(words, tags):
            w_id = self.vocab_dict[w] if w in self.vocab_dict.keys() else self.vocab_dict[UNKNOWN]
            t_id = self.pos_dict[t] if t in self.pos_dict.keys() else self.pos_dict[UNKNOWN]
            sent.add(w_id, t_id)
        
        tree_idx = self._predict_tree(session, model, sent)
        
        # New Dependency Tree object to convert label ids to actual labels, and words, pos tags, etc.
        num_token = tree_idx.count()
        tree_label = DependencyTree()   # final tree to store the label value of dependency
        for i in range(0, num_token):
            cur_head = tree_idx.get_head(i + 1)
            cur_label_id = tree_idx.get_label(i + 1)     # 0 is ROOT, actual index start from 1
            cur_label_name = self.rev_label_dict[cur_label_id] if cur_label_id in self.rev_label_dict.keys() else ""
            tree_label.add(words[i], tags[i], cur_head, cur_label_name)
        return tree_label
    
    def _predict_tree(self, session, model, sent, debug = False):
        """ Generate a greedy decoding parsing of a sent object with list of [word, tag]
            Return: dep parse tree, dep-label is in its id
        """
        target_num = len(self.rev_arc_labels)
        #print ("target number is %d" % target_num)
        config = Configuration(sent)    # create a parsing transition arc-standard system configuration, see (chen and manning.2014)
        while not config.is_terminal():
            features = transition_system.get_features(config, self.feature_tpl)   # 1-D list
            X = np.array([features])                            # convert 1-D list to ndarray size [1, dim]
            Y = np.array([[0] * target_num])

            # generate greedy prediction of the next_arc_id
            fetches = [model.loss, model.logit]   # fetch out prediction logit
            feed_dict = {}
            feed_dict[model.X] = X
            feed_dict[model.Y] = Y                         # dummy input y: 1D list of shape [, target_num]
            _, logit = session.run(fetches, feed_dict)     # not running eval_op, just for prediction

            pred_next_arc_id = int(np.argmax(logit))       # prediction of next arc_idx of 1 of (2*Nl +1)
            pred_next_arc = self.rev_arc_labels[pred_next_arc_id]    # 5-> L(2)   idx -> L(label_id)
            config.step(pred_next_arc)                     # Configuration Take One Step
            if (debug):
                print ("DEBUG: next arc idx is %d and next arc is %s" % (pred_next_arc_id, pred_next_arc))
        # When config is terminal, return the final dependence trees object
        dep_tree = config.tree
        return dep_tree

def load_model(name = 'zh'):
    ''' data_path e.g.: ./deepnlp/parser/data/zh
        ckpt_path e.g.: ./deepnlp/parser/ckpt/zh
        ckpt_file e.g.: ./deepnlp/parser/ckpt/zh/parser.ckpt.data-00000-of-00001
    '''
    data_path = os.path.join(pkg_path, "parse/data", name)                # Parser util data path
    ckpt_path = os.path.join(pkg_path, "parse/ckpt", name) # Parser model checkpoint path
    return ModelLoader(name, data_path, ckpt_path)
