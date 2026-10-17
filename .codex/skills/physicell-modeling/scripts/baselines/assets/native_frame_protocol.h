// Output-only compact native frame protocol v1; no model state or RNG changes.
#ifndef CLONEID_NATIVE_FRAME_PROTOCOL_H
#define CLONEID_NATIVE_FRAME_PROTOCOL_H
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <chrono>
#include <limits>
namespace cloneid_frame {
static const std::uint64_t max_cells=200000;
static const std::uint64_t max_frame_bytes=8000064;
inline bool capability_request(int argc,char** argv) {
 if(argc==2 && std::string(argv[1])=="--cloneid-frame-protocol") {
  std::cout<<"{\"protocol\":\"cloneid-native-frame\",\"version\":1,\"fields\":5,\"max_cells\":200000,\"max_frame_bytes\":8000064,\"acknowledged\":true}"<<std::endl;return true;
 }
 return false;
}
inline bool enabled() {
 const char* value=std::getenv("CLONEID_NATIVE_FRAME_PROTOCOL");
 if(!value || !*value) {return false;}
 if(std::string(value)!="1") {throw std::runtime_error("Unsupported CLONEID_NATIVE_FRAME_PROTOCOL version");}
 return true;
}
inline void initialize() {
 if(!enabled()) {return;}
 const std::uint32_t endian=1;
 if(*reinterpret_cast<const unsigned char*>(&endian)!=1 || sizeof(double)!=8 || !std::numeric_limits<double>::is_iec559) {throw std::runtime_error("Frame protocol requires IEEE754 little-endian float64");}
 std::ofstream out("stream.protocol",std::ios::binary|std::ios::trunc);
 out<<"CLONEID_NATIVE_FRAME_PROTOCOL 1 200000 5 8000064\n";out.close();
 if(!out) {throw std::runtime_error("Cannot write native frame handshake");}
}
template<class T> inline void scalar(std::ofstream& out,const T& value) {out.write(reinterpret_cast<const char*>(&value),sizeof(T));}
inline void save(std::uint64_t index,double minutes,std::uint64_t events=0) {
 // Bounds are checked BEFORE opening/truncating the sole payload file.
 const std::uint64_t number=PhysiCell::all_cells->size();
 if(number>max_cells) {throw std::runtime_error("200000-cell compact frame resource guard");}
 if(std::ifstream("stream.frame.ready").good() || std::ifstream("stream.frame.part").good() || std::ifstream("stream.ack").good()) {throw std::runtime_error("Unacknowledged/stale compact frame");}
 const std::uint32_t version=1,fields=5;const std::uint64_t payload=number*fields*sizeof(double),reserved=0;
 std::ofstream out("stream.frame.part",std::ios::binary|std::ios::trunc);
 out.write("CLIDFRM1",8);scalar(out,version);scalar(out,fields);scalar(out,index);scalar(out,minutes);scalar(out,number);scalar(out,payload);scalar(out,events);scalar(out,reserved);
 for(auto* cell:*PhysiCell::all_cells) {
  const double row[5]={cell->position[0],cell->position[1],cell->phenotype.volume.total,cell->phenotype.death.dead?1.:0.,static_cast<double>(cell->type)};
  out.write(reinterpret_cast<const char*>(row),sizeof(row));
 }
 out.close();
 if(!out || std::rename("stream.frame.part","stream.frame.ready")!=0) {throw std::runtime_error("Cannot publish compact native frame");}
 // Exactly one frame can exist. No simulation update advances before its ACK.
 while(true) {
  std::ifstream ack("stream.ack");std::uint64_t value;
  if(ack>>value) {
   if(value!=index) {throw std::runtime_error("Compact frame ACK index mismatch");}
   ack.close();
   if(std::remove("stream.ack")!=0) {throw std::runtime_error("Cannot remove compact ACK");}
   break;
  }
  std::this_thread::sleep_for(std::chrono::milliseconds(5));
 }
}
}
#endif
