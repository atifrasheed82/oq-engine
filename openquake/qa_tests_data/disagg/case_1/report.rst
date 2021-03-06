QA test for disaggregation case_1, taken from the disagg demo
=============================================================

============== ===================
checksum32     1,811,660,702      
date           2019-02-18T08:35:45
engine_version 3.4.0-git9883ae17a5
============== ===================

num_sites = 2, num_levels = 38

Parameters
----------
=============================== ==================
calculation_mode                'disaggregation'  
number_of_logic_tree_samples    0                 
maximum_distance                {'default': 100.0}
investigation_time              50.0              
ses_per_logic_tree_path         1                 
truncation_level                3.0               
rupture_mesh_spacing            5.0               
complex_fault_mesh_spacing      5.0               
width_of_mfd_bin                0.2               
area_source_discretization      10.0              
ground_motion_correlation_model None              
minimum_intensity               {}                
random_seed                     9000              
master_seed                     0                 
ses_seed                        42                
=============================== ==================

Input files
-----------
======================= ============================================================
Name                    File                                                        
======================= ============================================================
gsim_logic_tree         `gmpe_logic_tree.xml <gmpe_logic_tree.xml>`_                
job_ini                 `job.ini <job.ini>`_                                        
source_model_logic_tree `source_model_logic_tree.xml <source_model_logic_tree.xml>`_
======================= ============================================================

Composite source model
----------------------
========= ======= =============== ================
smlt_path weight  gsim_logic_tree num_realizations
========= ======= =============== ================
b1        1.00000 trivial(1)      1               
========= ======= =============== ================

Required parameters per tectonic region type
--------------------------------------------
====== =================== =========== ======================= =================
grp_id gsims               distances   siteparams              ruptparams       
====== =================== =========== ======================= =================
0      '[ChiouYoungs2008]' rjb rrup rx vs30 vs30measured z1pt0 dip mag rake ztor
1      '[ChiouYoungs2008]' rjb rrup rx vs30 vs30measured z1pt0 dip mag rake ztor
2      '[ChiouYoungs2008]' rjb rrup rx vs30 vs30measured z1pt0 dip mag rake ztor
3      '[ChiouYoungs2008]' rjb rrup rx vs30 vs30measured z1pt0 dip mag rake ztor
====== =================== =========== ======================= =================

Realizations per (GRP, GSIM)
----------------------------

::

  <RlzsAssoc(size=4, rlzs=1)
  0,'[ChiouYoungs2008]': [0]
  1,'[ChiouYoungs2008]': [0]
  2,'[ChiouYoungs2008]': [0]
  3,'[ChiouYoungs2008]': [0]>

Number of ruptures per tectonic region type
-------------------------------------------
================ ====== ==================== ============ ============
source_model     grp_id trt                  eff_ruptures tot_ruptures
================ ====== ==================== ============ ============
source_model.xml 0      Active Shallow Crust 15           15          
source_model.xml 1      Active Shallow Crust 1,440        1,440       
source_model.xml 2      Active Shallow Crust 617          617         
source_model.xml 3      Active Shallow Crust 164          164         
================ ====== ==================== ============ ============

============= =====
#TRT models   4    
#eff_ruptures 2,236
#tot_ruptures 2,236
#tot_weight   1,418
============= =====

Slowest sources
---------------
====== ========= ==== ===== ===== ============ ========= ========== ========= ========= =======
grp_id source_id code gidx1 gidx2 num_ruptures calc_time split_time num_sites num_split weight 
====== ========= ==== ===== ===== ============ ========= ========== ========= ========= =======
1      2         A    1     5     1,440        2.48046   1.32507    96        96        144    
2      3         S    5     7     617          1.24247   0.00124    10        10        617    
3      4         C    7     11    164          0.56427   2.05670    10        10        656    
0      1         P    0     1     15           0.02863   2.146E-05  1.00000   1         1.50000
====== ========= ==== ===== ===== ============ ========= ========== ========= ========= =======

Computation times by source typology
------------------------------------
==== ========= ======
code calc_time counts
==== ========= ======
A    2.48046   1     
C    0.56427   1     
P    0.02863   1     
S    1.24247   1     
==== ========= ======

Information about the tasks
---------------------------
================== ======= ======= ======= ======= =======
operation-duration mean    stddev  min     max     outputs
read_source_models 0.03723 NaN     0.03723 0.03723 1      
split_filter       0.24602 NaN     0.24602 0.24602 1      
classical          0.86723 1.09356 0.22845 2.80460 5      
build_hazard_stats 0.00653 0.00135 0.00558 0.00749 2      
================== ======= ======= ======= ======= =======

Fastest task
------------
taskno=3, weight=328, duration=0 s, sources="3 4"

======== ======= ======= === === =
variable mean    stddev  min max n
======== ======= ======= === === =
nsites   1.00000 0.0     1   1   4
weight   82      5.16398 76  88  4
======== ======= ======= === === =

Slowest task
------------
taskno=0, weight=321, duration=2 s, sources="4"

======== ======= ====== ======= === ==
variable mean    stddev min     max n 
======== ======= ====== ======= === ==
nsites   1.00000 0.0    1       1   99
weight   3.24747 12     1.50000 88  99
======== ======= ====== ======= === ==

Data transfer
-------------
================== =========================================================== =========
task               sent                                                        received 
read_source_models converter=313 B fnames=103 B                                4.05 KB  
split_filter       srcs=3.4 KB srcfilter=253 B seed=14 B                       101.78 KB
classical          group=99.11 KB param=4.02 KB src_filter=1.07 KB gsims=775 B 703.98 KB
build_hazard_stats pgetter=5.66 KB hstats=134 B N=28 B individual_curves=26 B  684 B    
================== =========================================================== =========

Slowest operations
------------------
======================== ========= ========= ======
operation                time_sec  memory_mb counts
======================== ========= ========= ======
total classical          4.33616   2.23828   5     
make_contexts            1.57992   0.0       2,236 
get_poes                 0.87923   0.0       2,236 
total split_filter       0.24602   2.49609   1     
total read_source_models 0.03723   0.71094   1     
aggregate curves         0.02113   1.11328   5     
saving probability maps  0.01805   0.0       1     
total build_hazard_stats 0.01307   1.60547   2     
combine pmaps            0.01189   1.54297   2     
managing sources         0.00761   0.0       1     
store source model       0.00416   0.0       1     
store source_info        0.00223   0.0       1     
saving statistics        0.00106   0.0       2     
compute mean             4.301E-04 0.0       1     
======================== ========= ========= ======