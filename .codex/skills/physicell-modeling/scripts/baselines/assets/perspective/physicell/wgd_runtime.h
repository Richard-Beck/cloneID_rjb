// Run-local WGD event extension. Native ordinary division remains untouched.
#include <array>
#include <fstream>
#include <iomanip>

namespace PhysiCell {
struct WGD_Event_Counts {
 std::array<long long,2> mitoses{{0,0}}, deaths{{0,0}}, divisions{{0,0}};
 long long conversions=0, logged=0;
};
static WGD_Event_Counts wgd_counts;
static bool wgd_enabled=true;
static double wgd_probability=0, wgd_death_low=0, wgd_death_high=0;
static std::ofstream wgd_event_log;
// XML death models otherwise share PhysiCell's global apoptosis cycle. Separate
// owned copies are required for distinct state-specific residence durations.
static std::array<Cycle_Model,2> wgd_apoptosis_models;

void wgd_configure() {
 for(int state=0;state<2;++state) {
  Cell_Definition* definition=cell_definitions_by_index[state];
  int index=definition->phenotype.death.find_death_model_index(PhysiCell_constants::apoptosis_death_model);
  const char* key=state?"dead_duration_high_minutes":"dead_duration_low_minutes";
  double duration=parameters.doubles(key);
  if(index<0 || !std::isfinite(duration) || duration<=0) {throw std::runtime_error("Invalid state apoptosis duration");}
  wgd_apoptosis_models[state]=*definition->phenotype.death.models[index];
  wgd_apoptosis_models[state].data.pCycle_Model=&wgd_apoptosis_models[state];
  wgd_apoptosis_models[state].transition_rate(0,1)=1.0/duration;
  wgd_apoptosis_models[state].phase_link(0,1).fixed_duration=true;
  definition->phenotype.death.models[index]=&wgd_apoptosis_models[state];
 }
 wgd_enabled=parameters.bools("wgd_interception_enabled");
 wgd_probability=parameters.doubles("wgd_probability");
 wgd_death_low=parameters.doubles("mitotic_death_low");
 wgd_death_high=parameters.doubles("mitotic_death_high");
 for(double value:{wgd_probability,wgd_death_low,wgd_death_high}) {
  if(!std::isfinite(value)||value<0||value>1) {throw std::runtime_error("Invalid WGD probability");}
 }
 wgd_event_log.open("mitotic_events.csv");
 wgd_event_log<<"time_minutes,cell_id,event,state_before,state_after,volume_before,volume_after,target_nuclear_after\n";
 wgd_event_log<<std::setprecision(17);
}

void wgd_log_event(Cell* cell,const std::string& event,int before,int after,double volume_before) {
 // A bounded trace demonstrates event ordering without unbounded output cost.
 if(wgd_counts.logged++>=256) {return;}
 wgd_event_log<<PhysiCell_globals.current_time<<","<<cell->ID<<","<<event<<","<<before<<","<<after<<","
              <<volume_before<<","<<cell->phenotype.volume.total<<","<<cell->phenotype.volume.target_solid_nuclear<<"\n";
}

bool wgd_before_m_exit(Cell* cell,Phenotype& phenotype,double dt) {
 if(!wgd_enabled) {return false;}
 const int old_state=cell->type==1?1:0;
 ++wgd_counts.mitoses[old_state];
 const double probability=old_state?wgd_death_high:wgd_death_low;
 const double mother_volume=phenotype.volume.total;
 // CURRENT-state mortality happens first. WGD cannot rescue this same event.
 if(probability>0 && UniformRandom()<probability) {
  ++wgd_counts.deaths[old_state];
  const int apoptosis_index=phenotype.death.find_death_model_index(PhysiCell_constants::apoptosis_death_model);
  if(apoptosis_index<0) {throw std::runtime_error("Missing apoptosis model");}
  cell->start_death(apoptosis_index);
  phenotype.flagged_for_division=false;
  phenotype.flagged_for_removal=false;
  wgd_log_event(cell,"mitotic_death",old_state,old_state,mother_volume);
  return true;
 }
 if(old_state==0 && wgd_probability>0 && UniformRandom()<wgd_probability) {
  ++wgd_counts.conversions;
  // Native conversion preserves current component volumes and geometry; targets
  // come from the high-state definition. No division/halving has happened.
  cell->convert_to_cell_definition(*cell_definitions_by_index[1]);
  cell->phenotype.volume.target_solid_cytoplasmic=cell_definitions_by_index[1]->phenotype.volume.target_solid_cytoplasmic;
  cell->phenotype.cycle.data.current_phase_index=0;
  cell->phenotype.cycle.data.elapsed_time_in_phase=0;
  cell->phenotype.flagged_for_division=false;
  cell->phenotype.flagged_for_removal=false;
  cell->set_total_volume(cell->phenotype.volume.total);
  cell->phenotype.geometry.update(cell,cell->phenotype,0);
  if(cell->phenotype.volume.total!=mother_volume) {throw std::runtime_error("WGD changed mother volume");}
  wgd_log_event(cell,"wgd_instead_of_division",0,1,mother_volume);
  return true;
 }
 ++wgd_counts.divisions[old_state];
 wgd_log_event(cell,"ordinary_division",old_state,old_state,mother_volume);
 return false; // original native phase exit, division flag and daughter split
}

void wgd_write_state(std::ofstream& out,double time) {
 std::array<long long,2> number{{0,0}},dead_number{{0,0}};
 std::array<double,2> volume{{0,0}};
 for(auto* cell:*all_cells) {
  int state=cell->type==1?1:0;
  if(cell->phenotype.death.dead) {++dead_number[state];continue;}
  ++number[state];volume[state]+=cell->phenotype.volume.total;
 }
 out<<std::setprecision(17)<<time<<","<<number[0]<<","<<number[1]<<","<<volume[0]<<","<<volume[1]<<","
    <<wgd_counts.mitoses[0]<<","<<wgd_counts.mitoses[1]<<","<<wgd_counts.deaths[0]<<","<<wgd_counts.deaths[1]<<","
    <<wgd_counts.conversions<<","<<wgd_counts.divisions[0]<<","<<wgd_counts.divisions[1]<<","
    <<dead_number[0]<<","<<dead_number[1]<<"\n";
}

void wgd_pair_check() {
 if(all_cells->size()!=6) {throw std::runtime_error("Pair check expects six IC cells");}
 std::ofstream out("mixed_pair_check.csv");
 out<<"pair,type_i,type_j,r_i,r_j,distance,velocity_x_i,velocity_x_j,pressure_i,pressure_j,repulsion_i,repulsion_j,adhesion_i,adhesion_j\n";
 out<<std::setprecision(17);
 for(int pair=0;pair<3;++pair) {
  Cell* a=(*all_cells)[2*pair];Cell* b=(*all_cells)[2*pair+1];
  a->velocity.assign(3,0);b->velocity.assign(3,0);a->state.simple_pressure=0;b->state.simple_pressure=0;
  a->add_potentials(b);b->add_potentials(a);
  out<<pair<<","<<a->type<<","<<b->type<<","<<a->phenotype.geometry.radius<<","<<b->phenotype.geometry.radius<<","
     <<fabs(a->position[0]-b->position[0])<<","<<a->velocity[0]<<","<<b->velocity[0]<<","<<a->state.simple_pressure<<","<<b->state.simple_pressure<<","
     <<a->phenotype.mechanics.cell_cell_repulsion_strength<<","<<b->phenotype.mechanics.cell_cell_repulsion_strength<<","
     <<a->phenotype.mechanics.cell_cell_adhesion_strength<<","<<b->phenotype.mechanics.cell_cell_adhesion_strength<<"\n";
 }
}
}
