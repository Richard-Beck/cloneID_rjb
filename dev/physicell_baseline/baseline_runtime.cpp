// Baseline runtime, consolidated without behavioral changes from the pooled validation adapter.
// Install as main.cpp; build with PhysiCell_custom_module_OBJECTS= (see workflow.md).
/*
###############################################################################
# If you use PhysiCell in your project, please cite PhysiCell and the version #
# number, such as below:                                                      #
#                                                                             #
# We implemented and solved the model using PhysiCell (Version x.y.z) [1].    #
#                                                                             #
# [1] A Ghaffarizadeh, R Heiland, SH Friedman, SM Mumenthaler, and P Macklin, #
#     PhysiCell: an Open Source Physics-Based Cell Simulator for Multicellu-  #
#     lar Systems, PLoS Comput. Biol. 14(2): e1005991, 2018                   #
#     DOI: 10.1371/journal.pcbi.1005991                                       #
#                                                                             #
# See VERSION.txt or call get_PhysiCell_version() to get the current version  #
#     x.y.z. Call display_citations() to get detailed information on all cite-#
#     able software used in your PhysiCell application.                       #
#                                                                             #
# Because PhysiCell extensively uses BioFVM, we suggest you also cite BioFVM  #
#     as below:                                                               #
#                                                                             #
# We implemented and solved the model using PhysiCell (Version x.y.z) [1],    #
# with BioFVM [2] to solve the transport equations.                           #
#                                                                             #
# [1] A Ghaffarizadeh, R Heiland, SH Friedman, SM Mumenthaler, and P Macklin, #
#     PhysiCell: an Open Source Physics-Based Cell Simulator for Multicellu-  #
#     lar Systems, PLoS Comput. Biol. 14(2): e1005991, 2018                   #
#     DOI: 10.1371/journal.pcbi.1005991                                       #
#                                                                             #
# [2] A Ghaffarizadeh, SH Friedman, and P Macklin, BioFVM: an efficient para- #
#     llelized diffusive transport solver for 3-D biological simulations,     #
#     Bioinformatics 32(8): 1256-8, 2016. DOI: 10.1093/bioinformatics/btv730  #
#                                                                             #
###############################################################################
#                                                                             #
# BSD 3-Clause License (see https://opensource.org/licenses/BSD-3-Clause)     #
#                                                                             #
# Copyright (c) 2015-2021, Paul Macklin and the PhysiCell Project             #
# All rights reserved.                                                        #
#                                                                             #
# Redistribution and use in source and binary forms, with or without          #
# modification, are permitted provided that the following conditions are met: #
#                                                                             #
# 1. Redistributions of source code must retain the above copyright notice,   #
# this list of conditions and the following disclaimer.                       #
#                                                                             #
# 2. Redistributions in binary form must reproduce the above copyright        #
# notice, this list of conditions and the following disclaimer in the         #
# documentation and/or other materials provided with the distribution.        #
#                                                                             #
# 3. Neither the name of the copyright holder nor the names of its            #
# contributors may be used to endorse or promote products derived from this   #
# software without specific prior written permission.                         #
#                                                                             #
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" #
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE   #
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE  #
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE   #
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR         #
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF        #
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS    #
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN     #
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)     #
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE  #
# POSSIBILITY OF SUCH DAMAGE.                                                 #
#                                                                             #
###############################################################################
*/

#include "./core/PhysiCell.h"
#include "./modules/PhysiCell_standard_modules.h"
using namespace BioFVM;
using namespace PhysiCell;
void phenotype_function(Cell*, Phenotype&, double);
void custom_function(Cell*, Phenotype&, double);
void contact_function(Cell*, Phenotype&, Cell*, Phenotype&, double);

#include <fstream>
#include <sstream>
#include <algorithm>
#include <stdexcept>

void create_cell_types( void )
{
	// set the random seed
	if (parameters.ints.find_index("random_seed") != -1)
	{
		SeedRandom(parameters.ints("random_seed"));
	}

	/*
	   Put any modifications to default cell definition here if you
	   want to have "inherited" by other cell types.

	   This is a good place to set default functions.
	*/

	initialize_default_cell_definition();
	cell_defaults.phenotype.secretion.sync_to_microenvironment( &microenvironment );

	cell_defaults.functions.volume_update_function = standard_volume_update_function;
	cell_defaults.functions.update_velocity = standard_update_cell_velocity;

	cell_defaults.functions.update_migration_bias = NULL;
	cell_defaults.functions.update_phenotype = NULL; // update_cell_and_death_parameters_O2_based;
	cell_defaults.functions.custom_cell_rule = NULL;
	cell_defaults.functions.contact_function = NULL;

	cell_defaults.functions.add_cell_basement_membrane_interactions = NULL;
	cell_defaults.functions.calculate_distance_to_membrane = NULL;

	/*
	   This parses the cell definitions in the XML config file.
	*/

	initialize_cell_definitions_from_pugixml();

	/*
	   This builds the map of cell definitions and summarizes the setup.
	*/

	build_cell_definitions_maps();

	/*
	   This intializes cell signal and response dictionaries
	*/

	setup_signal_behavior_dictionaries();

	/*
       Cell rule definitions
	*/

	setup_cell_rules();

	/*
	   Put any modifications to individual cell definitions here.

	   This is a good place to set custom functions.
	*/

	cell_defaults.functions.update_phenotype = phenotype_function;
	cell_defaults.functions.custom_cell_rule = custom_function;
	cell_defaults.functions.contact_function = contact_function;

	/*
	   This builds the map of cell definitions and summarizes the setup.
	*/

	display_cell_definitions( std::cout );

	return;
}

void setup_microenvironment( void )
{
	// set domain parameters

	// put any custom code to set non-homogeneous initial conditions or
	// extra Dirichlet nodes here.

	// initialize BioFVM

	initialize_microenvironment();

	return;
}

void setup_tissue( void )
{
 std::ifstream input(parameters.strings("initial_cells_file"));
 if(!input) { throw std::runtime_error("Cannot read initial_cells_file"); }
 std::string line; std::getline(input,line); int count=0;
 while(std::getline(input,line)) {
  std::replace(line.begin(),line.end(),',',' '); std::istringstream row(line);
  double x,y,elapsed,ns,cs,fluid; int phase;
  if(!(row>>x>>y>>phase>>elapsed>>ns>>cs>>fluid)) { throw std::runtime_error("Invalid IC row"); }
  Cell* c=create_cell(*cell_definitions_by_index[0]);
  c->assign_position(std::vector<double>{x,y,0.});
  c->phenotype.cycle.data.current_phase_index=phase;
  c->phenotype.cycle.data.elapsed_time_in_phase=elapsed;
  if(phase>0) { Phase& s=c->phenotype.cycle.model().phases[1]; if(s.entry_function) { s.entry_function(c,c->phenotype,0.); } }
  Volume& v=c->phenotype.volume;
  v.nuclear_solid=ns; v.cytoplasmic_solid=cs; v.solid=ns+cs;
  v.fluid=fluid; v.nuclear_fluid=fluid*ns/(ns+cs); v.cytoplasmic_fluid=fluid-v.nuclear_fluid;
  v.nuclear=ns+v.nuclear_fluid; v.cytoplasmic=cs+v.cytoplasmic_fluid;
  v.total=v.solid+fluid; v.fluid_fraction=fluid/v.total;
  c->set_total_volume(v.total); c->phenotype.geometry.update(c,c->phenotype,0.); ++count;
 }
 std::cout<<"Loaded latent initial state: "<<count<<" cells"<<std::endl;
}

std::vector<std::string> my_coloring_function( Cell* pCell )
{ return paint_by_number_cell_coloring(pCell); }

void phenotype_function( Cell* pCell, Phenotype& phenotype, double dt )
{ return; }

void custom_function( Cell* pCell, Phenotype& phenotype , double dt )
{ return; }

void contact_function( Cell* pMe, Phenotype& phenoMe , Cell* pOther, Phenotype& phenoOther , double dt )
{ return; }

/*
###############################################################################
# If you use PhysiCell in your project, please cite PhysiCell and the version #
# number, such as below:                                                      #
#                                                                             #
# We implemented and solved the model using PhysiCell (Version x.y.z) [1].    #
#                                                                             #
# [1] A Ghaffarizadeh, R Heiland, SH Friedman, SM Mumenthaler, and P Macklin, #
#     PhysiCell: an Open Source Physics-Based Cell Simulator for Multicellu-  #
#     lar Systems, PLoS Comput. Biol. 14(2): e1005991, 2018                   #
#     DOI: 10.1371/journal.pcbi.1005991                                       #
#                                                                             #
# See VERSION.txt or call get_PhysiCell_version() to get the current version  #
#     x.y.z. Call display_citations() to get detailed information on all cite-#
#     able software used in your PhysiCell application.                       #
#                                                                             #
# Because PhysiCell extensively uses BioFVM, we suggest you also cite BioFVM  #
#     as below:                                                               #
#                                                                             #
# We implemented and solved the model using PhysiCell (Version x.y.z) [1],    #
# with BioFVM [2] to solve the transport equations.                           #
#                                                                             #
# [1] A Ghaffarizadeh, R Heiland, SH Friedman, SM Mumenthaler, and P Macklin, #
#     PhysiCell: an Open Source Physics-Based Cell Simulator for Multicellu-  #
#     lar Systems, PLoS Comput. Biol. 14(2): e1005991, 2018                   #
#     DOI: 10.1371/journal.pcbi.1005991                                       #
#                                                                             #
# [2] A Ghaffarizadeh, SH Friedman, and P Macklin, BioFVM: an efficient para- #
#     llelized diffusive transport solver for 3-D biological simulations,     #
#     Bioinformatics 32(8): 1256-8, 2016. DOI: 10.1093/bioinformatics/btv730  #
#                                                                             #
###############################################################################
#                                                                             #
# BSD 3-Clause License (see https://opensource.org/licenses/BSD-3-Clause)     #
#                                                                             #
# Copyright (c) 2015-2022, Paul Macklin and the PhysiCell Project             #
# All rights reserved.                                                        #
#                                                                             #
# Redistribution and use in source and binary forms, with or without          #
# modification, are permitted provided that the following conditions are met: #
#                                                                             #
# 1. Redistributions of source code must retain the above copyright notice,   #
# this list of conditions and the following disclaimer.                       #
#                                                                             #
# 2. Redistributions in binary form must reproduce the above copyright        #
# notice, this list of conditions and the following disclaimer in the         #
# documentation and/or other materials provided with the distribution.        #
#                                                                             #
# 3. Neither the name of the copyright holder nor the names of its            #
# contributors may be used to endorse or promote products derived from this   #
# software without specific prior written permission.                         #
#                                                                             #
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" #
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE   #
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE  #
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE   #
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR         #
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF        #
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS    #
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN     #
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)     #
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE  #
# POSSIBILITY OF SUCH DAMAGE.                                                 #
#                                                                             #
###############################################################################
*/

#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <ctime>
#include <cmath>
#include <omp.h>
#include <fstream>

#include "./core/PhysiCell.h"
#include "./modules/PhysiCell_standard_modules.h"

// put custom code modules here!

// Declarations and definitions are supplied above in this consolidated file.

using namespace BioFVM;
using namespace PhysiCell;


int main(int argc,char* argv[]) {
 if(argc<2 || !load_PhysiCell_config_file(argv[1])) { return 1; }
 omp_set_num_threads(PhysiCell_settings.omp_num_threads);
 setup_microenvironment();
 create_cell_container_for_microenvironment(microenvironment,parameters.doubles("mechanics_voxel_size"));
 create_cell_types(); setup_tissue();
 set_save_biofvm_mesh_as_matlab(true); set_save_biofvm_data_as_matlab(true);
 set_save_biofvm_cell_data(true); set_save_biofvm_cell_data_as_custom_matlab(true);
 std::ifstream input(parameters.strings("sample_times_file"));
 std::vector<double> times; double time; while(input>>time) { times.push_back(time); }
 if(times.empty()) { std::cerr<<"No sample times"<<std::endl; return 2; }
 char name[2048]; sprintf(name,"%s/initial",PhysiCell_settings.folder.c_str());
 save_PhysiCell_to_MultiCellDS_v2(name,microenvironment,0.);
 size_t next=0; const long long last=(long long)ceil(PhysiCell_settings.max_time/diffusion_dt);
 for(long long step=0;step<=last;++step) {
  PhysiCell_globals.current_time=step*diffusion_dt;
  if(next<times.size() && PhysiCell_globals.current_time>=times[next]) {
   sprintf(name,"%s/output%08u",PhysiCell_settings.folder.c_str(),(unsigned int)next);
   save_PhysiCell_to_MultiCellDS_v2(name,microenvironment,PhysiCell_globals.current_time);
   std::cout<<"SAMPLE "<<next<<" time_min "<<PhysiCell_globals.current_time<<" cells "<<all_cells->size()<<std::endl; ++next;
  }
  if(next==times.size()) { break; }
  // Identically zero inactive substrate: no diffusion/decay solve is needed.
  ((Cell_Container*)microenvironment.agent_container)->update_all_cells(PhysiCell_globals.current_time);
  if(step%120==0) { std::cout<<"PROGRESS "<<PhysiCell_globals.current_time<<" "<<all_cells->size()<<std::endl; }
  if(all_cells->size()>200000) { std::cerr<<"200000-cell resource guard"<<std::endl; return 3; }
 }
 if(next!=times.size()) { std::cerr<<"Missing requested samples"<<std::endl; return 4; }
 std::cout<<"COMPLETE "<<next<<" requested samples"<<std::endl; return 0;
}
