# -*- coding: utf-8 -*-

#   Copyright (c) 2010-2016, MIT Probabilistic Computing Project
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import math
import numpy as np
import random                   # XXX

#from cgpm.regressions.forest import RandomForest
from cgpm.regressions.linreg import LinearRegression
from cgpm.venturescript.vscgpm import VsCGpm
from cgpm.utils import general as gu

from bayeslite import bayesdb_open
from bayeslite import bayesdb_register_metamodel
from bayeslite.metamodels.cgpm_metamodel import CGPM_Metamodel

# ------------------------------------------------------------------------------
# XXX Kepler source code.

kepler_source = """
[define make_cgpm (lambda ()
  (do
      ; Kepler's law.
    (assume keplers_law
      (lambda (apogee perigee)
        (let ((GM 398600.4418) (earth_radius 6378)
              (a (+ (* .5 (+ (abs apogee) (abs perigee))) earth_radius)))
          (/ (* (* 2 3.1415) (sqrt (/ (pow a 3) GM))) 60))))

    ; Internal samplers.
    (assume crp_alpha .5)

    (assume get_cluster_sampler
        (make_crp crp_alpha))

    (assume get_error_sampler
        (mem (lambda (cluster)
            (make_nig_normal 1 1 1 1))))

    ; Output simulators.
    (assume simulate_cluster_id
      (mem (lambda (rowid apogee perigee)
        (tag (atom rowid) (atom 1)
          (get_cluster_sampler)))))

    (assume simulate_error
      (mem (lambda (rowid apogee perigee)
          (let ((cluster_id (simulate_cluster_id rowid apogee perigee)))
            (tag (atom rowid) (atom 2)
              ((get_error_sampler cluster_id)))))))

    (assume simulate_period
      (mem (lambda (rowid apogee perigee)
        (+ (keplers_law apogee perigee)
           (simulate_error rowid apogee perigee)))))

    ; Simulators.
    (assume simulators (list simulate_cluster_id
                             simulate_error
                             simulate_period))))]

; Output observers.
[define observe_cluster_id
  (lambda (rowid apogee perigee value label)
      (observe (simulate_cluster_id ,rowid ,apogee ,perigee)
               (atom value) ,label))]

[define observe_error
  (lambda (rowid apogee perigee value label)
      (observe (simulate_error ,rowid ,apogee ,perigee) value ,label))]

[define observe_period
  (lambda (rowid apogee perigee value label)
    (let ((theoretical_period (run (sample (keplers_law ,apogee ,perigee))))
          (error (- value theoretical_period)))
      (observe_error rowid apogee perigee error label)))]

; List of observers.
[define observers (list observe_cluster_id
                        observe_error
                        observe_period)]

; List of inputs.
[define inputs (list 'apogee
                     'perigee)]

; Transition operator.
[define transition
  (lambda (N)
    (mh default one (* N 1000)))]
"""

# ------------------------------------------------------------------------------
# XXX Get some venturescript integration going.

bdb = bayesdb_open(':memory:')

bdb.sql_execute('''
    CREATE TABLE satellites_ucs (
        apogee,
        class_of_orbit,
        country_of_operator,
        launch_mass,
        perigee,
        period,
        -- Exposed variables.
        kepler_noise,
        kepler_cluster_id
        )
    ''')

for l, f in [
    ('geo', lambda x, y: x + y**2),
    ('leo', lambda x, y: math.sin(x + y)),
]:
    for x in xrange(10):
        for y in xrange(10):
            countries = ['US', 'Russia', 'China', 'Bulgaria']
            country = countries[random.randrange(len(countries))]
            mass = random.gauss(1000, 50)
            bdb.sql_execute('''
                INSERT INTO satellites_ucs
                    (country_of_operator, launch_mass, class_of_orbit,
                        apogee, perigee, period)
                    VALUES (?,?,?,?,?,?)
            ''', (country, mass, l, x, y, f(x, y)))

D = bdb.sql_execute('SELECT * FROM satellites_ucs').fetchall()

bdb.execute('''
    CREATE POPULATION satellites FOR satellites_ucs (
        apogee NUMERICAL,
        class_of_orbit CATEGORICAL,
        country_of_operator CATEGORICAL,
        launch_mass NUMERICAL,
        perigee NUMERICAL,
        period NUMERICAL,
        kepler_noise NUMERICAL,
        kepler_cluster_id CATEGORICAL
        )
    ''')

bdb.execute('''
    ESTIMATE CORRELATION FROM PAIRWISE COLUMNS OF satellites
    ''').fetchall()

cgpmt = CGPM_Metamodel(
    cgpm_registry={
        'venturescript': VsCGpm,
        'linreg': LinearRegression,
        })
bayesdb_register_metamodel(bdb, cgpmt)

bdb.execute('''
    CREATE GENERATOR g0 FOR satellites USING cgpm (
        MODEL kepler_cluster_id, kepler_noise, period
            GIVEN apogee, perigee
            USING venturescript
                (source = "
                    {}
                    "))

    '''.format(kepler_source))


print 'INITIALIZING'
bdb.execute('INITIALIZE 1 MODEL FOR g0')

print 'ANALYZING'
bdb.execute('ANALYZE g0 FOR 1 ITERATION WAIT')

print 'DEP PROB'
print bdb.execute('''
    ESTIMATE DEPENDENCE PROBABILITY
        OF kepler_cluster_id WITH period BY satellites
    ''').fetchall()

print 'PRED PROB'
bdb.execute('''
    ESTIMATE PREDICTIVE PROBABILITY OF apogee FROM satellites LIMIT 1
    ''').fetchall()
bdb.execute('''
    ESTIMATE PREDICTIVE PROBABILITY OF kepler_cluster_id FROM satellites LIMIT 1
    ''').fetchall()
bdb.execute('''
    ESTIMATE PREDICTIVE PROBABILITY OF kepler_noise FROM satellites LIMIT 1
    ''').fetchall()
bdb.execute('''
    ESTIMATE PREDICTIVE PROBABILITY OF period FROM satellites LIMIT 1
    ''').fetchall()

assert False

bdb.execute('''
    ESTIMATE PROBABILITY OF period = 42
            GIVEN (apogee = 8 AND perigee = 7)
        BY satellites
    ''').fetchall()

bdb.execute('''
    SIMULATE apogee, perigee, period FROM satellites LIMIT 100
    ''').fetchall()

bdb.execute('DROP MODELS FROM g0')
bdb.execute('DROP GENERATOR g0')
bdb.execute('DROP GENERATOR g1')