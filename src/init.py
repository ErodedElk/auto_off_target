#!/usr/bin/env python3

# Auto off-target PoC
###
# Copyright  Samsung Electronics
# Samsung Mobile Security Team @ Samsung R&D Poland

#
# Init module
#

import logging
import sys
import shutil
import copy
import functools


class TypeUse:

    instance_id = 0

    def __init__(self, t_id, original_tid, is_pointer):
        self.id = TypeUse.instance_id
        TypeUse.instance_id += 1
        self.t_id = t_id  # the last known type of this object
        self.original_tid = original_tid
        self.is_pointer = is_pointer
        self.name = ""
        self.cast_types = []  # a list of all known types for this object
        # a list of tuples (containig type TypeUse, member number)
        self.offsetof_types = []
        # a reverse relationship to the types that were used in the offsetof
        # operator to retrieve this type
        # a list of tuples (member number, TypeUse object)
        self.contained_types = []
        # note: this list has a precedence over used_members when it
        # comes to init
        self.used_members = {}  # for a given type, maps used member of that type
        # to the related TypeUse objects

    def __str__(self):
        return f"[TypeUse] id = {self.id} t_id = {self.t_id} original_tid = {self.original_tid} " +\
            f"is_pointer = {self.is_pointer} name = '{self.name}' offsetof_types = {self.offsetof_types} " +\
            f"contained_types = {self.contained_types} used_members = {self.used_members} cast_types = {self.cast_types}"

    def __repr__(self):
        return f"[TypeUse id={self.id} t_id={self.t_id} original_tid={self.original_tid}]"


class Init:

    CAST_PTR_NO_MEMBER = -1
    MAX_RECURSION_DEPTH = 50

    def __init__(self, dbops, cutoff, deps, codegen, args):
        self.dbops = dbops
        self.cutoff = cutoff
        self.deps = deps
        self.codegen = codegen
        self.args = args
        self.member_usage_info = {}
        self.casted_pointers = {}
        self.offset_pointers = {}
        self.trace_cache = {}
        self.ptr_init_size = 1  # when initializing pointers use this a the number of objects
        self.array_init_max_size = 32  # when initializing arrays use this a an upper limimit
        self.tagged_vars_count = 0
        self.fpointer_stubs = []
        self.stub_names = set()

    # -------------------------------------------------------------------------

    # the aim of this function is to iterate through all types and within record types
    # find those that contain pointers
    # then, further analysis is performed to check if we can match the pointer member with
    # a corresponding size member
    # @belongs: init

    def _analyze_types(self):
        logging.info("Beginning type analysis")

        self._generate_member_size_info(
            self.dbops.fnmap.get_all(), self.dbops.typemap.get_all())

        logging.info(
            f"Type analysis complete. We captured data for {len(self.member_usage_info)} types")
        self._print_member_size_info()

        # records_with_pointers = {}

        # checked_record_types = 0
        # for t in self.dbops.db["types"]:
        #     if t["class"] == "record":
        #         checked_record_types += 1
        #         member_id = 0
        #         for t_id in t["refs"]:
        #             ref_t = self.dbops.typemap[t_id]
        #             ref_t = self._get_typedef_dst(ref_t)
        #             if ref_t["class"] == "pointer":
        #                 # so we have a pointer member
        #                 if t["id"] not in records_with_pointers:
        #                     records_with_pointers[t["id"]] = set()
        #                 records_with_pointers[t["id"]].add(t["refnames"][member_id])

        #             member_id += 1
        # logging.info(f"Type analysis shows {len(records_with_pointers)} record types with pointers out of {checked_record_types} checked record types")

        # keywords = [ "count", "size", "cnt", "len", "length", "sz" ]
        # matched = 0
        # one_to_one_match = 0
        # for t_id in records_with_pointers:
        #     t = self.dbops.typemap[t_id]
        #     member_id = 0
        #     matches = set()
        #     for ref_id in t["refs"]:
        #         ref_t = self.dbops.typemap[ref_id]
        #         ref_t = self._get_typedef_dst(ref_t)
        #         # the size is likely an integer or unsigned, so it has to be builtin
        #         matches = set()
        #         if ref_t["class"] == "builtin":
        #             name = t["refnames"][member_id]
        #             for key in keywords:
        #                 if key in name.lower():
        #                     matches.add(name)
        #         member_id += 1

        #     if len(matches) > 0:
        #         matched += 1
        #         logging.info(f"For type id {t_id} we have possible matches: {records_with_pointers[t_id]} <-> {matches}")
        #         if len(matches) == 1 and len(records_with_pointers[t_id]) == 1:
        #             one_to_one_match += 1

        # logging.info(f"In total, we found matches in {matched} types, including {one_to_one_match} 1-1 matches")
    # -------------------------------------------------------------------------

    # helper functions
    # @belongs: init
    def _print_member_size_info(self):
        count = 0
        logging.info(f"We have info for {len(self.member_usage_info)} structs")
        for t_id in self.member_usage_info:
            name = self.dbops.typemap[t_id]["str"]
            logging.info(f"Struct : {name} ")
            index = 0
            for member in self.member_usage_info[t_id]:
                if len(member) > 0:
                    count += 1
                    logging.info(
                        f"\tWe have some data for member {self.dbops.typemap[t_id]['refnames'][index]}")
                    if "value" in member:
                        logging.info(f"\t\tvalue: {member['value']}")
                    elif "member_idx" in member:
                        done = False
                        for m in member['member_idx']:
                            done = True
                            name = self.dbops.typemap[t_id]['refnames'][m]
                            logging.info(f"\t\tmember_idx: {name}")
                        if not done:
                            logging.info(
                                f"detected member_idx: {member['member_idx']}")

                    elif "name_size" in member:
                        done = False
                        for m in member['name_size']:
                            done = True
                            name = self.dbops.typemap[t_id]['refnames'][m]
                            logging.info(f"\t\tname_size: {name}")
                        if not done:
                            logging.info(
                                f"datected name_size: {member['name_size']}")
                    else:
                        logging.info(f"\t\tPrinting raw data {member}")
                index += 1

        logging.info(
            f"We have found {count} structs with some info on array sizes")

    # @belongs: init
    def _generate_constraints_check(self, var_name, size_constraints):
        str = ""
        if "min_val" in size_constraints:
            str += f"if ({var_name} < {size_constraints['min_val']})" + "{\n"
            str += f"\t{var_name} = {size_constraints['min_val']};\n"
            str += "}\n"
        if "max_val" in size_constraints:
            str += f"if ({var_name} > {size_constraints['max_val']})" + "{\n"
            str += f"\t{var_name} %= {size_constraints['max_val']};\n"
            str += f"\t{var_name} += 1;\n"
            str += "}\n"
        return str

    # use member_type_info to get the right member init ordering for a record type
    # return a list consisting of member indices to generate init for
    # @belongs: init
    def _get_members_order(self, t):
        ret = []
        size_constraints = []
        if t['class'] != 'record':
            return None, None
        ret = [i for i in range(len(t['refnames']))]
        size_constraints = [{} for i in range(len(t['refnames']))]

        t_id = t['id']

        if t_id not in self.member_usage_info:
            return ret, size_constraints

        fields_no = len(t['refnames'])
        for i in range(fields_no):
            field_name = t['refnames'][i]

            if field_name == "__!attribute__" or field_name == "__!anonrecord__" or \
                    field_name == "__!recorddecl__" or field_name == "__!anonenum__":
                continue

            is_in_use = self._is_member_in_use(t, t['str'], i)
            if is_in_use:
                # now we know that the member is in use, let's check if we have some info for it
                usage_info = self.member_usage_info[t_id][i]
                if len(usage_info) == 0:
                    continue

                # we have some usage info for this member
                size_member_index = None
                match = False
                if "name_size" in usage_info:
                    if len(usage_info["name_size"]) == 1:
                        size_member_index = next(iter(usage_info["name_size"]))
                        match = True
                    else:
                        # we have more than 1 candidates, let's see if
                        # some additional info could help
                        # first, we check if the same member is a single member for member_idx
                        if "member_idx" in usage_info and len(usage_info["member_idx"]) == 1:
                            for m in usage_info["name_size"]:
                                item = next(iter(usage_info["member_idx"]))
                                if item[0] == t_id and m == item[1]:
                                    size_member_index = m
                                    match = True
                                    break
                        # if no single match found, also check "member_size"
                        if not match and "member_size" in usage_info and len(usage_info["member_size"]) == 1:
                            for m in usage_info["name_size"]:
                                item = next(iter(usage_info["member_size"]))
                                if item[0] == t_id and m == item[1]:
                                    size_member_index = m
                                    match = True
                                    break
                    if match:
                        # either a single name_size or multiple name_size but a single
                        # member_idx or a single member_size that matches one of the name_size ones
                        size_constraints[i]['size_member'] = size_member_index
                        if size_member_index not in size_constraints:
                            size_constraints[size_member_index] = {}
                        # since we use one member as a size for another, the value range needs to be meaningful
                        size_constraints[size_member_index]["min_val"] = 1
                        if "max_val" not in size_constraints[size_member_index]:
                            max_val = self.array_init_max_size
                            if "value" in usage_info:
                                val = usage_info["value"]
                                if val > 0:
                                    if val != max_val:
                                        # leverage the fact that we noticed array reference at a concrete offset
                                        max_val = val
                            size_constraints[size_member_index]["max_val"] = max_val
                        size_member_index = [size_member_index]

                    else:
                        size_member_index = usage_info["name_size"]
                    match = True

                if match is False and "member_idx" in usage_info:
                    item = usage_info["member_idx"]
                    if len(item) == 1:
                        item = next(iter(item))
                        if t_id == item[0]:
                            size_member_index = item[1]
                            size_constraints[i]["size_member_idx"] = size_member_index
                            if size_member_index not in size_constraints:
                                size_constraints[size_member_index] = {}
                            # since we use one member as a size for another, the value range needs to be meaningful
                            size_constraints[size_member_index]["min_val"] = 1
                            if "max_val" not in size_constraints[size_member_index]:
                                max_val = self.array_init_max_size
                                if "value" in usage_info:
                                    val = usage_info["value"]
                                    if val > 0:
                                        if val != max_val:
                                            # leverage the fact that we noticed array reference at a concrete offset
                                            max_val = val
                                size_constraints[size_member_index]["max_val"] = max_val
                            size_member_index = [size_member_index]

                            match = True

                if match is False and "member_size" in usage_info:
                    item = usage_info["member_size"]
                    if len(item) == 1:
                        item = next(iter(item))
                        if t_id == item[0]:
                            size_member_index = item[1]
                            size_constraints[i]["size_member_idx"] = size_member_index
                            if size_member_index not in size_constraints:
                                size_constraints[size_member_index] = {}
                            # since we use one member as a size for another, the value range needs to be meaningful
                            size_constraints[size_member_index]["min_val"] = 1
                            if "max_val" not in size_constraints[size_member_index]:
                                max_val = self.array_init_max_size
                                if "value" in usage_info:
                                    val = usage_info["value"]
                                    if val > 0:
                                        if val != max_val:
                                            # leverage the fact that we noticed array reference at a concrete offset
                                            max_val = val
                                size_constraints[size_member_index]["max_val"] = max_val
                            size_member_index = [size_member_index]

                            match = True

                if match is False and "value" in usage_info:
                    val = usage_info["value"]
                    if (val < 0):
                        val = -val
                    if val != 0:
                        # val would be the largest const index used on an array + 1 (so it's array size)
                        size_constraints[i]["size_value"] = val

                if size_member_index is not None:
                    current_index = i
                    for sm_index in size_member_index:
                        if sm_index > current_index:
                            # swap members such that the size member is initialized before the buffer member
                            ret[current_index] = sm_index
                            ret[sm_index] = current_index
                            logging.info(
                                f"Swapping members {current_index} and {sm_index} in type {t['str']}")
                            current_index = sm_index

                if "index" in usage_info:
                    logging.info(
                        f"Index detected in usage info for member {field_name}")
                    max_val = -1
                    if "max_val" in size_constraints[i]:
                        max_val = size_constraints[i]["max_val"]
                    if (max_val == -1) or ((usage_info["index"] - 1) < max_val):
                        # the 'index' member is collected based on a const-size array reference
                        # therefore if one exists, we are certain that the value is no greater than the size - 1
                        size_constraints[i]["max_val"] = usage_info["index"] - 1

                        if "min_val" not in size_constraints:
                            size_constraints[i]["min_val"] = 0

        return ret, size_constraints

    # @belongs: init
    def _is_size_type(self, t):
        ints = {'char', 'signed char', 'unsigned char', 'short', 'unsigned short', 'int', 'unsigned int',
                'long', 'unsigned long', 'long long', 'unsigned long long', 'unsigned __int128'}
        t = self.dbops._get_typedef_dst(t)
        if t["str"] in ints:
            return True
        return False

    # @belongs: init
    def _get_record_type(self, base_type):
        # remove typedef to pointer type
        base_type = self.dbops._get_typedef_dst(base_type)
        # remove pointer
        base_type = self.dbops.typemap[self.dbops._get_real_type(
            base_type['id'])]
        # remove typedef to record type)
        base_type = self.dbops._get_typedef_dst(base_type)
        return base_type

    # @belongs: init but unused
    def _find_local_init_or_assign(self, local_id, ord, func):
        matching_derefs = []
        for deref in func["derefs"]:
            if deref["kind"] in ["init", "assign"]:
                lhs = deref["offsetrefs"][0]
                if lhs["kind"] == "local" and lhs["id"] == local_id and deref["ord"] < ord:
                    matching_derefs.append(deref)
        return matching_derefs

    # @belongs: init
    def _is_pointer_like_type(self, t):
        t = self.dbops._get_typedef_dst(t)
        # normal pointer
        if t["class"] == "pointer":
            return True
        # address held in 64 int
        if self._is_size_type(t) and t["size"] == 64:
            return True
        return False

    # function generates usage info for record members
    # we are looking for struct types with pointer members and try to find the corresponding
    # member with the same type that may represent the pointer's size
    # The extra info we collect:
    #
    # for pointer-like members:
    # - ['name_size']  : other struct members that can represent size -> detected by name, e.g., s->array <=> s->array_size
    # - ['member_idx'] : other struct members that can represent size -> detected by index use, e.g., s->array[s->member]
    # - ['value']      :constant sizes -> detected by the use of const indices, e.g., s->array[20]
    # - ['member_size']: other struct members taht can represent size -> detected by comparison, e.g. for (; s->index < 10; ), if (s->index <= 9)
    # for size-like members:
    # - ['index']      : upper limit for members used as an index in a const array (any), e.g. array[s->index], where array is of size 20
    # @belongs: init
    def _generate_member_size_info(self, funcs, types):
        logging.info(f"will generate size info")

        for func in funcs:
            logging.info(f"processing {func['name']}")
            derefs = func["derefs"]
            for deref in derefs:
                # get info from 'array' kind derefs, ignore complicated cases
                if deref["kind"] == "array" and deref["basecnt"] == 1:
                    base_offsetref = deref["offsetrefs"][0]
                    # info for array members
                    if base_offsetref["kind"] == "member":
                        member_deref = derefs[base_offsetref["id"]]
                        record_type = self._get_record_type(
                            self.dbops.typemap[member_deref["type"][-1]])
                        record_id = record_type["id"]
                        member_id = member_deref["member"][-1]
                        member_type = self.dbops.typemap[record_type["refs"][member_id]]
                        member_type = self.dbops._get_typedef_dst(member_type)
                        # we only care about poiners
                        if self._is_pointer_like_type(member_type):
                            # add info about member usage (implicit by existence)
                            if record_id not in self.member_usage_info:
                                self.member_usage_info[record_id] = [
                                    {} for k in record_type["refs"]]
                            member_data = self.member_usage_info[record_id][member_id]

                            # add info about potential size
                            if deref["offset"] != 0:
                                if "value" not in member_data:
                                    member_data["value"] = deref["offset"]+1
                                else:
                                    member_data["value"] = max(
                                        member_data["value"], deref["offset"]+1)
                            # add info about potential index member
                            for index_offsetref in deref["offsetrefs"][1:]:
                                # same base member index
                                if index_offsetref["kind"] == "member":
                                    size_deref = derefs[index_offsetref["id"]]
                                    size_record_type = self._get_record_type(
                                        self.dbops.typemap[size_deref["type"][-1]])
                                    size_record_id = size_record_type["id"]
                                    size_member_id = size_deref["member"][-1]
                                    size_member_type = self.dbops.typemap[size_record_type["refs"]
                                                                          [size_member_id]]
                                    size_member_type = self.dbops._get_typedef_dst(
                                        size_member_type)
                                    if self._is_size_type(size_member_type):
                                        if "member_idx" not in member_data:
                                            member_data["member_idx"] = set()
                                        member_data["member_idx"].add(
                                            (size_record_id, size_member_id))
                            # add info about potential size member
                            if len(deref["offsetrefs"]) == 2:
                                index_offsetref = deref["offsetrefs"][1]
                                item = next(
                                    cs for cs in func["csmap"] if cs["id"] == deref["csid"])
                                if "cf" in item and item["cf"] in ["do", "while", "for", "if"]:
                                    # find condition
                                    for cderef in derefs:
                                        if cderef["kind"] == "cond" and cderef["offset"] == deref["csid"]:
                                            if len(cderef["offsetrefs"]) == 1 and cderef["offsetrefs"][0]["kind"] == "logic":
                                                lderef = derefs[cderef["offsetrefs"][0]["id"]]
                                                if lderef["offset"] in [10, 12, 15] and len(lderef["offsetrefs"]) == 2:
                                                    if index_offsetref == lderef["offsetrefs"][0]:
                                                        size_offsetref = lderef["offsetrefs"][1]
                                                        if size_offsetref["kind"] == "integer":
                                                            size = size_offsetref["id"]
                                                            if lderef["offset"] == 12:
                                                                size += 1
                                                            if "value" not in member_data:
                                                                member_data["value"] = size
                                                            else:
                                                                member_data["value"] = max(
                                                                    member_data["value"], size)
                                                        if size_offsetref["kind"] == "member":
                                                            size_deref = derefs[size_offsetref["id"]]
                                                            size_record_type = self._get_record_type(
                                                                self.dbops.typemap[size_deref["type"][-1]])
                                                            size_record_id = size_record_type["id"]
                                                            size_member_id = size_deref["member"][-1]
                                                            size_member_type = self.dbops.typemap[
                                                                size_record_type["refs"][size_member_id]]
                                                            size_member_type = self.dbops._get_typedef_dst(
                                                                size_member_type)
                                                            if self._is_size_type(size_member_type):
                                                                if "member_size" not in member_data:
                                                                    member_data["member_size"] = set(
                                                                    )
                                                                member_data["member_size"].add(
                                                                    (size_record_id, size_member_id))
                # add info about members as index to const arrays
                if deref["kind"] == "array" and deref["basecnt"] == 1 and len(deref["offsetrefs"]) == 2:
                    base_offsetref = deref["offsetrefs"][0]
                    index_offsetref = deref["offsetrefs"][1]
                    if index_offsetref["kind"] == "member":
                        # try find array size
                        size = 0
                        if base_offsetref["kind"] == "member":
                            base_deref = derefs[base_offsetref["id"]]
                            base_record_type = self._get_record_type(
                                self.dbops.typemap[base_deref["type"][-1]])
                            base_member_id = base_deref["member"][-1]
                            base_member_type = self.dbops._get_typedef_dst(
                                self.dbops.typemap[base_record_type["refs"][base_member_id]])
                            if base_member_type["class"] == "const_array":
                                size = self._get_const_array_size(
                                    base_member_type)
                        elif base_offsetref["kind"] == "global":
                            global_deref = self.dbops.globalsidmap[base_offsetref["id"]]
                            global_type = self.dbops._get_typedef_dst(
                                self.dbops.typemap[global_deref["type"]])
                            if global_type["class"] == "const_array":
                                size = self._get_const_array_size(global_type)
                        elif base_offsetref["kind"] == "local":
                            local_deref = func["locals"][base_offsetref["id"]]
                            local_type = self.dbops._get_typedef_dst(
                                self.dbops.typemap[local_deref["type"]])
                            if local_type["class"] == "const_array":
                                size = self._get_const_array_size(local_type)
                        if size != 0:
                            # add size info
                            index_deref = derefs[index_offsetref["id"]]
                            index_record_type = self._get_record_type(
                                self.dbops.typemap[index_deref["type"][-1]])
                            index_record_id = index_record_type["id"]
                            index_member_id = index_deref["member"][-1]
                            if index_record_id not in self.member_usage_info:
                                self.member_usage_info[index_record_id] = [
                                    {} for k in index_record_type["refs"]]
                            index_data = self.member_usage_info[index_record_id][index_member_id]
                            if "index" in index_data:
                                index_data["index"] = max(
                                    size, index_data["index"])
                            index_data["index"] = size

        for _t in types:
            t = self._get_record_type(_t)
            if t["class"] == "record":
                # try guessing size member from name
                # do only once
                record_type = t
                record_id = t["id"]

                for member_id in range(len(record_type["refs"])):
                    m_t = self.dbops.typemap[record_type["refs"][member_id]]
                    # looking for a pointer struct members
                    if self._is_pointer_like_type(m_t):

                        if record_id not in self.member_usage_info:
                            self.member_usage_info[record_id] = [
                                {} for k in record_type["refs"]]
                        member_data = self.member_usage_info[record_id][member_id]

                        if "name_size" not in member_data:
                            sizecount = 0
                            sizes = []
                            sizematch = ["size", "len", "num",
                                         "count", "sz", "n_", "cnt", "length"]
                            for size_member_id in range(len(record_type["refs"])):
                                size_type = self.dbops.typemap[record_type["refs"]
                                                               [size_member_id]]
                                if self._is_size_type(size_type):
                                    # name matching
                                    member_name = record_type["refnames"][member_id]
                                    size_name = record_type["refnames"][size_member_id]
                                    if member_name in size_name:
                                        for match in sizematch:
                                            if match in size_name.replace(member_name, '').lower():
                                                sizecount += 1
                                                sizes.append(size_member_id)
                                                break
                            # TODO: solve priority instead of adding all maybe
                            if sizecount > 1:
                                pass
                            if len(sizes) > 0:
                                member_data["name_size"] = set()
                                member_data["name_size"] |= set(sizes)

    # -------------------------------------------------------------------------

    # Walk through pointer or array types and extract underlying record type
    # Returns (RT,TPD) pair where:
    #  RT: underlying record type
    #  TPD: if the underlying record type was a typedef this is the original typedef type
    # In case record type cannot be resolved returns (None,None) pair
    # @belongs: init?
    def _resolve_record_type(self, TID, TPD=None):

        T = self.dbops.typemap[TID]
        if T["class"] == "record" or T["class"] == "record_forward":
            return T, TPD
        elif T["class"] == "pointer" or T["class"] == "const_array" or T["class"] == "incomplete_array":
            TPD = None
            return self._resolve_record_type(T["refs"][0], TPD)
        elif T["class"] == "typedef":
            if TPD is None:
                TPD = T
            return self._resolve_record_type(T["refs"][0], TPD)
        elif T["class"] == "attributed":
            return self._resolve_record_type(T["refs"][0], TPD)
        else:
            return None, None

    # -------------------------------------------------------------------------

    # To fuzz or not to fuzz, that is the question!
    # This function decides this the same way Hamlet would do:
    # - if it's a builtin type -> we fuzz it
    # - otherwise -> don't fuzz it
    # @belongs: init
    def _to_fuzz_or_not_to_fuzz(self, t):

        cl = t["class"]

        if cl == "builtin" or cl == "enum":
            return True
        elif cl == "const_array" or cl == "incomplete_array":
            dst_type = self.dbops.typemap[t["refs"][0]]
            dst_type = self.dbops._get_typedef_dst(dst_type)
            return self._to_fuzz_or_not_to_fuzz(dst_type)

        return False

    # -------------------------------------------------------------------------

    # @belongs: init
    def _get_cast_ptr_data(self, type, member_number=CAST_PTR_NO_MEMBER):
        type_to_check = None
        if member_number == Init.CAST_PTR_NO_MEMBER:
            type_to_check = type
        else:
            # it's a structured type
            type_to_check = self.dbops.typemap[type['refs'][member_number]]

        # if not self._is_void_ptr(type_to_check):
        #    return None, False

        t_id = type["id"]
        _t_id = self.dbops._get_real_type(t_id)
        _type = self.dbops.typemap[_t_id]
        logging.debug(
            f"Getting casted data for {self.codegen._get_typename_from_type(type)}")
        if _type["class"] == "record":
            # if the type is a record, we keep the cast data under the type, not it's
            # pointer, so we need to get the pointer destination first
            t_id = _t_id
            type = _type

        entry = None
        single_init = False

        if t_id in self.casted_pointers:
            entry = self.casted_pointers[t_id]
            if entry is None:
                logging.info(f"Entry is null for type {t_id}")
            if member_number in entry:
                if len(entry[member_number]) == 1:
                    # we've detected that there is only one cast for this structure and member
                    single_init = True
            else:
                logging.debug(
                    f"Member {member_number} not found for entry for type {t_id}")
                entry = None
        else:
            typename = self.codegen._get_typename_from_type(type)
            logging.debug(f"No cast information found for type {typename}")

        if entry is not None and member_number != Init.CAST_PTR_NO_MEMBER:
            logging.debug(
                f"Member {type['refnames'][member_number]} found in the void pointers map: {entry}, t_id: {t_id}")
        elif entry is not None:
            logging.debug(
                f"Type {t_id} found in the void pointers map")
        else:
            logging.debug(f"Type {type['id']} found in the void pointers map ")

        offset_types = None
        if t_id in self.offset_pointers:
            offset_types = self.offset_pointers[t_id]
        return entry, single_init, offset_types

    # -------------------------------------------------------------------------

    # @belongs: init
    def _get_tagged_var_name(self):
        self.tagged_vars_count += 1
        return f"\"aot_var_{self.tagged_vars_count}\""

    # -------------------------------------------------------------------------

    # Given variable name and type, generate correct variable initialization code.
    # For example:
    # name = var, type = struct A*
    # code: struct A* var = (struct A*)malloc(sizeof(struct A*));

    # @belongs: init
    def _generate_var_init(self, name, type, res_var, pointers, level=0, skip_init=False, known_type_names=None, cast_str=None, new_types=None,
                           entity_name=None, init_obj=None, fuse=None, fid=None, count=None):
        # in case of typedefs we need to get the first non-typedef type as a point of
        # reference

        if fuse is not None:
            fuse += 1
            if fuse > Init.MAX_RECURSION_DEPTH:
                logging.error("Max recursion depth reached")
                with open(self.args.output_dir + "/aot_recursion_error.txt", "w") as file:
                    file.write(
                        f"Max recursion depth reached while generating var init\n")
                if self.args.ignore_recursion_errors:
                    return "// Recursion loop ignored on an attempt to initialize this variable. Manual init required.\n", False, True 
                else:
                    raise Exception("Breaking execution due to error")

        if False == self.args.init:
            return "", False, False

        type = self.dbops._get_typedef_dst(type)

        cl = type["class"]
        if self.args.debug_vars_init:
            logging.info(
                f"generating var init for {name} cl {cl} type {type['id']}")

        t_id = type["id"]

        if t_id in self.used_types_data:
            type = self.used_types_data[t_id]
            if self.args.debug_vars_init:
                logging.info(
                    f"used type found for {t_id}. Type id is {type['id']}")
        str = ""
        # if level == 0 and skip_init == False:
        #     str = "{} = ".format(res_var)
        # else:
        #     str = ""

        # Init types based on type class:
        # 1) builtin:
        # memset based on sizeof
        # 2) typedef:
        # memset based on sizeof
        # 3) struct:
        # memset based on sizeof
        # 4) enum:
        # we could initialize just to the first member or use a generic
        # init with constraints on the value
        # 5) function pointer
        # We could generate a function with a matching signature
        # and assign the pointer to that function.
        # Alternatively we could also just do a memset
        # 6) incomplete_array
        # That would be something like, e.g. char* argv[]
        # We probably need to have a param that controls how many elements
        # to create. Once we know that, we initialize like for const_array.
        # 7) const_array
        # That would be something like, e.g. char* argv[10]
        # We need to create a loop, inside of which we generate
        # initializer for each member
        # 8) pointer
        # memset based on sizeof

        # The right memory init is hard to get. As long as we have non-pointer types
        # it's moderately easy: just allocate a block of memory and assign selected data
        # to it. However, once we operate on pointer, it is very hard to
        # know if a pointer is just a single object or a group of objects.
        # If it's a single object we could just allocate another one and again populate
        # it with data. If it's an array or a void pointer, it might be very hard to tell.
        # The only way to tell is by executing the code and detecting usage patterns.
        # Luckily, e.g. in the kernel code it should be moderately easy to tell - copy_from_user
        # would only perform a shallow copy of pointers - if no further copy is performed,
        # it's already an indication of something being wrong. On the other hand, another
        # call to copy_from_user on a pointer member should indicate the size and type of
        # memory pointed to by the pointer.

        # we need to override copy_from user and simiar methods and dynamically allocate
        # memory on request
        alloc = False
        is_array = False
        loop_count = 0
        name_change = False

        dst_type = type

        typename = self.codegen._get_typename_from_type(type)

        if init_obj is not None and init_obj.t_id != dst_type["id"] and type["class"] == "record_forward":
            # see if we might be dealing with record_forward of the same record
            _tmp_id = init_obj.t_id
            _dst_tid = dst_type['id']
            if init_obj.is_pointer:
                _tmp_id = self.dbops._get_real_type(_tmp_id)
                _dst_tid = self.dbops._get_real_type(_dst_tid)
            init_type = self.dbops.typemap[_tmp_id]
            _dst_type = self.dbops.typemap[_dst_tid]
            if init_type["class"] == "record" and _dst_type["class"] == "record_forward" and init_type["str"] == _dst_type["str"]:
                if self.args.debug_vars_init:
                    logging.info(
                        f"Updating dst_type from record_fwd {dst_type['id']} to record {init_obj.t_id}")
                type = self.dbops.typemap[init_obj.t_id]
                dst_type = type
                cl = type["class"]
                t_id = type["id"]

        if "pointer" == cl or "const_array" == cl or "incomplete_array" == cl:

            # let's find out the last component of the name
            index_dot = name.rfind(".")
            index_arrow = name.rfind("->")
            index = -1
            if index_dot > index_arrow:
                index = index_dot
            else:
                index = index_arrow

            pointer = False
            member_name = name
            name_base = ""
            if index != -1:
                name_base = name[:index]
                if index == index_dot:
                    index += 1
                else:
                    index += 2
                    pointer = True
                member_name = name[index:]

            if "const_array" == cl:
                dst_type = type["refs"][0]
                dst_size = self.dbops.typemap[dst_type]["size"] // 8
                if dst_size != 0:
                    array_count = (type["size"] // 8) // dst_size
                else:
                    array_count = 0
                sizestr = "[{}]".format(array_count)
                typename = typename.replace(sizestr, "")
                typename = typename.strip()

                # if level == 0 or skip_init == False:
                #     str += "aot_memory_init_ptr(&{}, sizeof({}), {});\n".format(name,
                #                                                               typename, array_count)
                #     alloc = True
                is_array = True
                loop_count = array_count
                if 0 == loop_count:
                    if self.args.debug_vars_init:
                        logging.warning(
                            "special case: adding a single member to a const array")
                    loop_count = 1  # this is a special corner case -> we already allocated memory for 1 member
                    str += "// increasing the loop count to 1 for a const array of size 0\n"
            elif "incomplete_array" == cl and type['size'] == 0:
                is_array = True
                loop_count = 0
                if self.args.debug_vars_init:
                    logging.warning(
                        "special case: adding a single member to a const array")
                loop_count = 1  # this is a special corner case -> we already allocated memory for 1 member
                str += "// increasing the loop count to 1 for a const array of size 0\n"
            else:
                dst_type = self.dbops._get_typedef_dst(
                    self.dbops.typemap[type["refs"][0]])
                # special case among pointers are function pointers
                if "pointer" == cl:
                    # assuming pointer has a single ref - the destination type
                    dst_cl = dst_type["class"]

                    # # let's find out the last component of the name
                    # index_dot = name.rfind(".")
                    # index_arrow = name.rfind("->")
                    # index = -1
                    # if index_dot > index_arrow:
                    #     index = index_dot
                    # else:
                    #     index = index_arrow

                    # pointer = False
                    # member_name = ""
                    # name_base = ""
                    # if index != -1:
                    #     name_base = name[:index]
                    #     if index == index_dot:
                    #         index += 1
                    #     else:
                    #         index += 2
                    #         pointer = True
                    #     member_name = name[index:]

                    if "function" == dst_cl:
                        stub_name = name.replace(".", "_")
                        stub_name = stub_name.replace("->", "_")
                        stub_name = stub_name.replace("[", "_")
                        stub_name = stub_name.replace("]", "")
                        stub_name = stub_name.replace("(", "")
                        stub_name = stub_name.replace(")", "")
                        stub_name = stub_name.replace("*", "")
                        stub_name = stub_name.strip()
                        stub_name = f"aotstub_{stub_name.split()[-1]}"

                        if stub_name not in self.stub_names:
                            self.stub_names.add(stub_name)
                        else:
                            suffix=1
                            while f"{stub_name}_{suffix}" in self.stub_names:
                                suffix += 1
                            stub_name = f"{stub_name}_{suffix}"
                            self.stub_names.add(stub_name)

                        tmp_str, fname = self.codegen._generate_function_stub(dst_type["id"], stubs_file=False,
                                                                              fpointer_stub=True, stub_name=stub_name)

                        str = f"aot_memory_init_func_ptr(&{name}, {fname});\n"
                        # str = f"{name} = {fname};\n"
                        if tmp_str not in self.fpointer_stubs:
                            self.fpointer_stubs.append(tmp_str)
                        return str, alloc, False
                    elif (dst_type["id"] in pointers and (pointers.count(dst_type["id"]) > 1 or member_name in ["prev", "next"]) or
                            (member_name in ["pprev"] and self.dbops._get_real_type(dst_type["id"]) in pointers)):
                        # we have already initialized the structure the pointer points to
                        # so we have to break the loop
                        if self.args.debug_vars_init:
                            logging.info(f"breaking linked list for {name}")
                        str += f"/* note: {name} pointer is already initialized (or we don't want a recursive init loop) */\n"
                        if member_name in ["prev", "next"]:
                            if pointer:
                                str += f"aot_memory_setptr(&{name},{name_base});\n"
                            else:
                                str += f"aot_memory_setptr(&{name},&{name_base});\n"
                        elif member_name in ["pprev"]:
                            if pointer:
                                str += f"aot_memory_setptr(&{name},&{name_base});\n"
                            else:
                                str += f"aot_memory_setptr(&{name},&{name_base}.next);\n"

                        return str, alloc, False
                    elif known_type_names != None and dst_type["class"] == "record_forward" and dst_type["str"] not in known_type_names:
                        recfwd_found = False
                        if init_obj is not None and init_obj.t_id != dst_type["id"]:
                            # see if we might be dealing with record_forward of the same record
                            _tmp_id = init_obj.t_id
                            if init_obj.is_pointer:
                                _tmp_id = self.dbops._get_real_type(_tmp_id)
                            init_type = self.dbops.typemap[_tmp_id]
                            if init_type["class"] == "record" and dst_type["class"] == "record_forward" and init_type["str"] == dst_type["str"]:
                                if self.args.debug_vars_init:
                                    logging.info(
                                        f"Detected that we are dealing with a pointer to record forward but we know the real record")
                                recfwd_found = True
                        if not recfwd_found:
                            str += f"/*{name} left uninitialized as it's not used */\n"
                            if self.args.debug_vars_init:
                                logging.info(
                                    f"/*{name} left uninitialized as it's not used */\n")
                            return str, False, False

                    # pointers are allocated as arrays of size >= 1
                    is_array = True

                    if dst_cl == "pointer" or dst_cl == "const_array":
                        name_change = True
                elif "incomplete_array" == cl:
                    is_array = True

                if count is None:
                    loop_count = self.ptr_init_size
                else:
                    loop_count = count

                null_terminate = False
                user_init = False
                user_fuzz = None
                tag = False
                value = None
                min_value = None
                max_value = None
                protected = False
                if level == 0 and self.dbops.init_data is not None and entity_name in self.dbops.init_data:
                    if self.args.debug_vars_init:
                        logging.info(
                            f"Detected that {entity_name} has user-provided init")
                    item = self.dbops.init_data[entity_name]
                    for entry in item["items"]:
                        entry_type = "unknown"
                        if "type" in entry:
                            entry_type = entry["type"]
                            if " *" not in entry_type:
                                entry_type = entry_type.replace("*", " *")

                        if name in entry["name"] or entry_type == self.codegen._get_typename_from_type(type):
                            if self.args.debug_vars_init:
                                logging.info(
                                    f"In {entity_name} we detected that item {name} of type {entry_type} has a user-specified init")

                            if "size" in entry:
                                loop_count = entry["size"]
                                if "size_dep" in entry:
                                    # check if the dependent param is present (for functions only)
                                    dep_id = entry["size_dep"]["id"]
                                    dep_add = entry["size_dep"]["add"]
                                    dep_names = []
                                    dep_user_name = ""
                                    dep_found = False
                                    for i in item["items"]:
                                        if i["id"] == dep_id:
                                            dep_names = i["name"]
                                            if "user_name" in i:
                                                dep_user_name = i["user_name"]
                                            else:
                                                logging.error(
                                                    "user_name not in data spec and size_dep used")
                                                sys.exit(1)
                                            dep_found = True
                                            break
                                    if dep_found and fid:
                                        f = self.dbops.fnidmap[fid]
                                        if f is not None and len(dep_names) > 0:
                                            for index in range(1, len(f["types"])):
                                                if "name" in f["locals"][index - 1] and f["locals"][index - 1]["parm"]:
                                                    param_name = f["locals"][index - 1]["name"]
                                                    if param_name in dep_names:
                                                        loop_count = dep_user_name
                                                        if dep_add != 0:
                                                            loop_count = f"{loop_count} + {dep_add}"

                            if "nullterminated" in entry:
                                if entry["nullterminated"] == "True":
                                    null_terminate = True
                            if "tagged" in entry:
                                if entry["tagged"] == "True":
                                    tag = True
                            if "value" in entry:
                                value = entry["value"]
                            if "min_value" in entry:
                                min_value = entry["min_value"]
                            if "max_value" in entry:
                                max_value = entry["max_value"]
                            if "fuzz" in entry:
                                if entry["fuzz"] is True:
                                    user_fuzz = 1
                                else:
                                    user_fuzz = 0
                            if "protected" in entry and entry["protected"] == "True":
                                protected = True
                            user_init = True
                            break  # no need to look further

                if user_init:
                    entry = None
                    single_init = False
                else:
                    entry, single_init, offset_types = self._get_cast_ptr_data(
                        type)
                    if self.args.debug_vars_init:
                        logging.info(
                            f"it's a pointer init obj {init_obj} offset types {offset_types} type {type['id']}")

                    final_objs = []
                    if offset_types is not None and init_obj is not None:
                        if self.args.debug_vars_init:
                            logging.info(f"init_obj is {init_obj}")
                        to_process = []
                        to_keep = []
                        if self.args.debug_vars_init:
                            logging.info(
                                f"this init_obj has {len(init_obj.offsetof_types)} offsetof_types")
                        for types, members, obj in init_obj.offsetof_types:
                            to_keep = []  # indices to remove
                            for i in range(len(offset_types)):
                                _types, _members = offset_types[i]
                                if _types == types and _members == members:
                                    to_keep.append(i)
                                    to_process.append((types, members, obj))
                                    break
                        tmp = []
                        if len(to_keep) < len(offset_types):
                            if self.args.debug_vars_init:
                                logging.info(
                                    f"We reduced offset_types by using derefs trace info")
                                logging.info(
                                    f"Before it was {len(offset_types)} now it is {len(to_keep)}")
                            for i in to_keep:
                                tmp.append(offset_types[i])
                            offset_types = tmp
                        # at this point, we should be left with only those offsetof derefs that
                        # are found in the derefs trace
                        # there is still a possibility that further offsetof uses were applied
                        # to the already offset types -> let's find out all of the potential outcomes
                        final = []
                        while (len(to_process) > 0):
                            types, members, obj = to_process.pop()
                            if len(obj.offsetof_types) == 0:
                                # if there is an unlikely sequence of offsetof operators we are interested
                                # in the last one in the trace applied only
                                final.append((types, members))
                                final_objs.append(obj)
                                if self.args.debug_vars_init:
                                    logging.info(
                                        "No more offset types, the object is final")
                            else:
                                for _types, _members, _obj in obj.offsetof_types:
                                    to_process.append((_types, _members, _obj))
                        if len(final) > 0:
                            if self.args.debug_vars_init:
                                logging.info("updating offset types")
                            offset_types = final

                    if offset_types is not None and (0 == len(offset_types)):
                        offset_types = None

                if not user_init and offset_types is not None:  # and level == 0
                    str_tmp = ""
                    # this type has been used to pull in its containing type
                    str_tmp += "\n// smart init : we detected that the type is used in the offsetof operator"

                    # we will have to emit a fresh variable for the containing type
                    variant = ""
                    variant_num = 1
                    i = 0
                    for i in range(len(offset_types)):

                        types, members = offset_types[i]
                        # the destination type of offsetof goes first
                        _dst_t = self.dbops.typemap[types[0]]
                        typename = self.codegen._get_typename_from_type(_dst_t)
                        _dst_tid = _dst_t["id"]
                        if new_types != None:
                            new_types.add(_dst_tid)
                        fuzz = int(self._to_fuzz_or_not_to_fuzz(_dst_t))
                        name_tmp = name.replace(typename, "")
                        name_tmp = name_tmp.replace(".", "_")
                        name_tmp = name_tmp.replace("->", "_")
                        name_tmp = name_tmp.replace("[", "_")
                        name_tmp = name_tmp.replace("]", "_")
                        name_tmp = name_tmp.replace(" ", "")
                        name_tmp = name_tmp.replace("(", "")
                        name_tmp = name_tmp.replace(")", "")
                        name_tmp = name_tmp.replace("*", "")
                        fresh_var_name = f"{name_tmp}_offset_{i}"
                        is_vla_struct = False
                        extra_padding = 0
                        if _dst_t["class"] == "record":
                            last_tid = _dst_t["refs"][-1]
                            last_type = self.dbops.typemap[last_tid]
                            if last_type["class"] == "const_array" or (last_type["class"] == "incomplete_array" and last_type["size"] == 0):
                                array_count = self._get_const_array_size(
                                    last_type)
                                if 0 == array_count:
                                    # a special case of variable lenght array as the last member of a struct
                                    is_vla_struct = True
                                    last_type_name = self.codegen._get_typename_from_type(
                                        last_type).replace("[0]", "")
                                    extra_padding = f"sizeof({last_type_name})"

                        if not is_vla_struct:
                            str_tmp += f"\n{typename} {fresh_var_name};"
                        else:
                            str_tmp += f"\n// making extra space for the variable lenght array at the end of the struct"
                            str_tmp += f"\n{typename}* {fresh_var_name};"
                            str_tmp += f"\naot_memory_init_ptr(&{fresh_var_name}, sizeof({typename}) + {extra_padding}, 1 /* count */, 0 /* fuzz */, \"\");"
                            fresh_var_name = f"(*{fresh_var_name})"

                        if self.args.debug_vars_init:
                            logging.info(
                                f"typename is {typename} name_tmp is {name_tmp} fresh_var_name is {fresh_var_name}")
                        comment = ""
                        if len(offset_types) > 1:
                            comment = "//"
                            variant = f"variant {variant_num}"
                            variant_num += 1
                        str_tmp += "\n{} // smart init {}\n".format(
                            comment, variant)
                        # str += "{} aot_memory_init_ptr(&{}, sizeof({}), {} /* count */, {} /* fuzz */);\n".format(
                        #     comment, name, typename, self.ptr_init_size, fuzz)
                        # pointers.append(dst_t["id"])

                        obj = None
                        if i < len(final_objs):
                            obj = final_objs[i]
                        elif init_obj is not None:
                            if self.args.debug_vars_init:
                                logging.info(
                                    f"not enough objects in final_objs: len is {len(final_objs)}, init_obj: {init_obj} ")
                            raise Exception("Breaking execution due to error")
                        if obj == init_obj:
                            if self.args.debug_vars_init:
                                logging.info(f"Object is the same {obj}")
                            # sys.exit(1)
                        else:
                            if self.args.debug_vars_init:
                                logging.info(
                                    f"Object is different obj is {obj}")

                        # we have to assign our top-level
                        # parameter to the right member of the containing type
                        member_name = ""
                        for i in range(len(members)):
                            member_no = members[i]
                            _tmp_t = self.dbops.typemap[types[i]]
                            deref = ""

                            _tmp_name = _tmp_t['refnames'][member_no]
                            if _tmp_name == "__!anonrecord__" or _tmp_name == "__!recorddecl__" or _tmp_name == "__!anonenum__":
                                continue

                            if len(member_name) > 0:
                                if _tmp_t["class"] == "pointer":
                                    deref = "->"
                                else:
                                    deref = "."
                            member_name += f"{deref}{_tmp_name}"

                        str_tmp += f"{name} = &{fresh_var_name}.{member_name};\n"

                        if self.args.debug_vars_init:
                            logging.info("variant c")
                        brk = False
                        if len(offset_types) > 1 and variant_num > 2 and self.args.single_init_only:
                            str_tmp = ""
                        else:
                            _str_tmp, alloc_tmp, brk = self._generate_var_init(fresh_var_name,
                                                                            _dst_t,
                                                                            res_var,
                                                                            pointers[:],
                                                                            level,
                                                                            skip_init,
                                                                            known_type_names=known_type_names,
                                                                            cast_str=None,
                                                                            new_types=new_types,
                                                                            init_obj=obj,
                                                                            fuse=fuse)
                            str_tmp += _str_tmp
                        i += 1

                        if len(offset_types) > 1 and variant_num > 2:
                            str_tmp = str_tmp.replace("\n", "\n//")
                            if str_tmp.endswith("//"):
                                str_tmp = str_tmp[:-2]

                        str += str_tmp
                        alloc = False
                        if brk:
                            return str, False, brk


                    # if len(offset_types) == 1:
                    if self.args.debug_vars_init:
                        logging.info("Returning after detecting offsetof")
                    # logging.info(f"str is {str}, offset_types len is {len(offset_types)}, str_tmp is {str_tmp}")
                    return str, alloc, False
                else:  # todo: consider supporting offsetof + cast at level 0

                    force_ptr_init = False
                    if not user_init and entry is not None and init_obj is not None:
                        if self.args.debug_vars_init:
                            logging.info(
                                f"this is not user init, entry is {entry}")
                        # entry is not None, which means we have some casts
                        # let's check if we have some additional hints in our init object
                        # we keed all casts history in the cast_types array, but the
                        # latest type is always stored in the t_id/original_tid
                        latest_tid = init_obj.original_tid
                        if latest_tid in entry[Init.CAST_PTR_NO_MEMBER]:
                            if self.args.debug_vars_init:
                                logging.info(
                                    f"Current object's tid {latest_tid} detected in entry - will use that one")
                            entry = copy.deepcopy(entry)
                            entry[Init.CAST_PTR_NO_MEMBER] = [latest_tid]
                            single_init = True
                        else:
                            if self.args.debug_vars_init:
                                logging.info(
                                    f"current tid {latest_tid} not found in entry")

                        skipped_count = 0
                        for _tid in entry[Init.CAST_PTR_NO_MEMBER]:
                            active_type = self.dbops.typemap[self.dbops._get_real_type(
                                t_id)]
                            active_type = self.dbops._get_typedef_dst(
                                active_type)
                            casted_type = self.dbops.typemap[self.dbops._get_real_type(
                                _tid)]
                            casted_type = self.dbops._get_typedef_dst(
                                casted_type)
                            struct_types = ["record", "record_forward"]
                            if active_type["class"] in struct_types and casted_type["class"] not in struct_types:
                                skipped_count += 1

                        if not skip_init and skipped_count == len(entry[Init.CAST_PTR_NO_MEMBER]):
                            # we have to do it since there will be no init in the other case
                            force_ptr_init = True

                    if not single_init or force_ptr_init:
                        typename = typename.replace("*", "", 1)
                        typename = typename.strip()
                        if user_fuzz is None:
                            fuzz = int(self._to_fuzz_or_not_to_fuzz(dst_type))
                        else:
                            fuzz = user_fuzz

                        extra_padding = None
                        # test for a corner case: a struct with the last member being a const array of size 0
                        if dst_type["class"] == "record" and len(dst_type["refs"]) > 0:
                            last_tid = dst_type["refs"][-1]
                            last_type = self.dbops.typemap[last_tid]
                            if last_type["class"] == "const_array" or (last_type["class"] == "incomplete_array" and last_type["size"] == 0):
                                array_count = self._get_const_array_size(
                                    last_type)
                                if 0 == array_count:
                                    # corner case detected -> it means that we have to add allocate some special room
                                    # to accommodate for that
                                    last_type_name = self.codegen._get_typename_from_type(
                                        last_type).replace("[0]", "")
                                    extra_padding = f"sizeof({last_type_name})"
                                    logging.warning(
                                        f"Our current item {name} of type {typename} has a zero-sized array")

                        # check all the types the object was casted to and select the size which
                        # fits the largest of those types
                        multiplier = None

                        names = set()
                        if init_obj is not None and not user_init:
                            if len(init_obj.cast_types) > 0:
                                max = dst_type["size"]
                                for _obj_tid, _obj_orig_tid, _is_ptr in init_obj.cast_types:
                                    final_tid = _obj_orig_tid
                                    if _is_ptr:
                                        final_tid = self.dbops._get_real_type(
                                            final_tid)
                                    final_type = self.dbops.typemap[final_tid]
                                    names.add(
                                        self.codegen._get_typename_from_type(final_type))

                                    final_type = self.dbops._get_typedef_dst(
                                        final_type)
                                    if final_type["size"] > max:
                                        max = final_type["size"]
                                if max > dst_type["size"]:
                                    if dst_type["size"] == 0:
                                        if max % 8 == 0:
                                            multiplier = f"{max // 8}"
                                        else:
                                            multiplier = f"{max // 8} + 1"
                                    else:
                                        multiplier = (
                                            max // dst_type["size"]) + 1
                                        multiplier = f"sizeof({typename})*{multiplier}"
                                    if extra_padding:
                                        multiplier = f"{multiplier} + {extra_padding.replace('*', '', 1)}"
                                        str += f"// smart init: allocating extra space for a 0-size const array member\n"
                                    str += f"// smart init: this object has many casts: using larger count to accommodate the biggest casted type\n"
                                    str += f"// the other types are: {names}\n"

                        addsize = 0
                        if not user_init and typename == "char" and fuzz != 0 and not null_terminate:
                            # we have a var of type char* and we want to fuzz it
                            # in this case we allocate more bytes and 0-terminate just in case
                            addsize = 32
                        elif not user_init and typename == "void" and fuzz != 0 and not null_terminate:
                            # we have a var of type void* and we want to fuzz it
                            # in this case we allocate more bytes and 0-terminate just in case
                            addsize = 128

                        cnt = loop_count
                        if count is None and addsize != 0:
                            cnt = loop_count + addsize

                        tagged_var_name = 0
                        if tag:
                            tagged_var_name = self._get_tagged_var_name()
                        if multiplier is None:
                            if extra_padding is None:
                                str += "aot_memory_init_ptr(&{}, sizeof({}), {} /* count */, {} /* fuzz */, {});\n".format(
                                    name, typename, cnt, fuzz, tagged_var_name)
                            else:
                                # a rather rare case of extra padding being non-zero
                                str += f"// smart init: allocating extra space for a 0-size const array member\n"
                                str += "aot_memory_init_ptr(&{}, sizeof({}) + {}, {} /* count */, {} /* fuzz */, {});\n".format(
                                    name, typename, extra_padding.replace("*", "", 1), cnt, fuzz, tagged_var_name)
                        else:
                            str += "aot_memory_init_ptr(&{}, {}, {} /* count */, {} /* fuzz */, {});\n".format(
                                name, multiplier, cnt, fuzz, tagged_var_name)
                        if addsize and not null_terminate:
                            # use intermediate var to get around const pointers
                            str += f"tmpname = {name};\n"
                            str += f"tmpname[{cnt} - 1] = '\\0';\n"

                        if null_terminate:
                            str += f"{name}[{loop_count} - 1] = 0;\n"

                        if value is not None:
                            str += f"#ifdef KLEE\n"
                            str += "if (AOT_argc == 1) {\n"
                            str += f"    klee_assume(*{name} == {value});\n"
                            str += "}\n"
                            str += f"#endif\n"
                        if min_value is not None:
                            str += f"if ({name} < {min_value}) {name} = {min_value};\n"
                        if max_value is not None:
                            str += f"if ({name} > {max_value}) {name} = {max_value};\n"
                        if tag:
                            str += f"aot_tag_memory({name}, sizeof({typename}) * {cnt}, 0);\n"
                            str += f"aot_tag_memory(&{name}, sizeof({name}), 0);\n"
                        if protected:
                            str += f"aot_protect_ptr(&{name});\n"

                    if not skip_init and entry is not None:
                        # we are dealing with a pointer for which we have found a cast in the code

                        variant = ""
                        variant_num = 1
                        cast_done = False
                        for _dst_tid in entry[Init.CAST_PTR_NO_MEMBER]:
                            _dst_t = self.dbops.typemap[_dst_tid]
                            typename = self.codegen._get_typename_from_type(
                                _dst_t)

                            active_type = self.dbops.typemap[self.dbops._get_real_type(
                                t_id)]
                            active_type = self.dbops._get_typedef_dst(
                                active_type)
                            casted_type = self.dbops.typemap[self.dbops._get_real_type(
                                _dst_tid)]
                            casted_type = self.dbops._get_typedef_dst(
                                casted_type)
                            struct_types = ["record", "record_forward"]
                            if active_type["class"] in struct_types and casted_type["class"] not in struct_types:
                                if self.args.debug_vars_init:
                                    logging.info(
                                        "will not consider cast of structural type to non-structural type")
                                continue

                            if new_types != None:
                                new_types.add(_dst_tid)
                            fuzz = int(self._to_fuzz_or_not_to_fuzz(_dst_t))

                            comment = ""
                            # str += "{} aot_memory_init_ptr(&{}, sizeof({}), {} /* count */, {} /* fuzz */);\n".format(
                            #     comment, name, typename, self.ptr_init_size, fuzz)
                            # pointers.append(dst_t["id"])
                            if self.args.debug_vars_init:
                                logging.info("variant d")
                            cast_done = True
                            brk = False
                            if not single_init and self.args.single_init_only:
                                str_tmp = ""
                            else:                            
                                str_tmp, alloc_tmp, brk = self._generate_var_init(name,
                                                                                _dst_t,
                                                                                res_var,
                                                                                pointers[:],
                                                                                level,
                                                                                skip_init,
                                                                                known_type_names=known_type_names,
                                                                                cast_str=typename,
                                                                                new_types=new_types,
                                                                                init_obj=init_obj,
                                                                                fuse=fuse)
                                if not single_init:
                                    comment = "//"
                                    variant = f"variant {variant_num}"
                                    variant_num += 1
                                str_tmp = "\n{} // smart init (a) {}: we've found that this pointer var is casted to another type: {}\n{}".format(
                                    comment, variant, typename, str_tmp)
                            # logging.info(str_tmp)
                            if not single_init:
                                str_tmp = str_tmp.replace(
                                    "\n", "\n//")
                                if str_tmp.endswith("//"):
                                    str_tmp = str_tmp[:-2]
                            str += str_tmp
                            if brk:
                                return str, False, brk

                        # len(entry[Generator.CAST_PTR_NO_MEMBER]) == 1 and cast_done == True:
                        if cast_done == True:
                            if self.args.debug_vars_init:
                                logging.info(
                                    "Returning after detecting a cast")
                            return str, alloc, False
                    alloc = True
        else:
            if (level == 0 and skip_init == False) or cl in ["builtin", "enum"]:
                fuzz = int(self._to_fuzz_or_not_to_fuzz(type))
                typename = self.codegen._get_typename_from_type(type)
                if typename in ["struct", "enum", "union"]:  # annonymous type
                    typename = name

                null_terminate = False
                tag = False
                value = None
                min_value = None
                max_value = None
                protected = False
                mul = 1
                isPointer = False
                if level == 0 and self.dbops.init_data is not None and entity_name in self.dbops.init_data:
                    if self.args.debug_vars_init:
                        logging.info(
                            f"Detected that {entity_name} has user-provided init")
                    item = self.dbops.init_data[entity_name]
                    for entry in item["items"]:
                        entry_type = "unknown"
                        if "type" in entry:
                            entry_type = entry["type"]
                            if " *" not in entry_type:
                                entry_type = entry_type.replace("*", " *")

                        if name in entry["name"] or entry_type == self.codegen._get_typename_from_type(type):
                            if self.args.debug_vars_init:
                                logging.info(
                                    f"In {entity_name} we detected that item {name} of type {entry_type} has a user-specified init")
                            if "nullterminated" in entry:
                                if entry["nullterminated"] == "True":
                                    null_terminate = True
                            if "tagged" in entry:
                                if entry["tagged"] == "True":
                                    tag = True
                            if "value" in entry:
                                value = entry["value"]
                            if "min_value" in entry:
                                min_value = entry["min_value"]
                            if "max_value" in entry:
                                max_value = entry["max_value"]
                            if "user_name" in entry:
                                name = entry["user_name"]
                            if "size" in entry:
                                mul = entry["size"]
                                if "size_dep" in entry:
                                    # check if the dependent param is present (for functions only)
                                    dep_id = entry["size_dep"]["id"]
                                    dep_add = entry["size_dep"]["add"]
                                    dep_names = []
                                    dep_user_name = ""
                                    dep_found = False
                                    for i in item["items"]:
                                        if i["id"] == dep_id:
                                            dep_names = i["name"]
                                            if "user_name" in i:
                                                dep_user_name = i["user_name"]
                                            else:
                                                logging.error(
                                                    "user_name not in data spec and size_dep used")
                                                sys.exit(1)
                                            dep_found = True
                                            break
                                    if dep_found and fid:
                                        f = self.dbops.fnidmap[fid]
                                        if f is not None and len(dep_names) > 0:
                                            for index in range(1, len(f["types"])):
                                                if "name" in f["locals"][index - 1] and f["locals"][index - 1]["parm"]:
                                                    param_name = f["locals"][index - 1]["name"]
                                                    if param_name in dep_names:
                                                        mul = dep_user_name
                                                        if dep_add != 0:
                                                            mul = f"{mul} + {dep_add}"

                            if "pointer" in entry:
                                if entry["pointer"] == "True":
                                    isPointer = True

                            if "protected" in entry and entry["protected"] == "True":
                                protected = True

                            user_init = True
                            break  # no need to look further
                tagged_var_name = 0
                if tag:
                    tagged_var_name = self._get_tagged_var_name()
                if not isPointer:
                    str += "aot_memory_init(&{}, sizeof({}), {} /* fuzz */, {});\n".format(
                        name, typename, fuzz, tagged_var_name)
                else:
                    # special case: non-pointer value is to be treated as a pointer
                    str += f"{typename}* {name}_ptr;\n"
                    str += f"aot_memory_init_ptr(&{name}_ptr, sizeof({typename}), {mul}, 1 /* fuzz */, {tagged_var_name});\n"

                if value is not None:
                    str += "#ifdef KLEE\n"
                    str += "if (AOT_argc == 1) {\n"
                    if not isPointer:
                        str += f"    klee_assume({name} == {value});\n"
                    else:
                        str += f"    klee_assume(*{name} == {value});\n"
                    str += "}\n"
                    str += "#endif\n"
                if min_value is not None:
                    str += f"if ({name} < {min_value}) {name} = {min_value};\n"
                if max_value is not None:
                    str += f"if ({name} > {max_value}) {name} = {max_value};\n"
                if tag:
                    if not isPointer:
                        str += f"aot_tag_memory(&{name}, sizeof({typename}), 0);\n"
                    else:
                        str += f"aot_tag_memory({name}_ptr, sizeof({typename}) * {mul}, 0);\n"
                        str += f"aot_tag_memory(&{name}_ptr, sizeof({name}_ptr), 0);\n"

                if protected and isPointer:
                    str += f"aot_protect_ptr(&{name}_ptr);\n"

                if isPointer:
                    str += f"{name} = ({typename}){name}_ptr;\n"

        if cl == "record" and t_id not in self.used_types_data and level > 1:
            typename = self.codegen._get_typename_from_type(
                self.dbops.typemap[t_id])
            return f"// {name} of type {typename} is not used anywhere\n", False, False

        # if level == 0 and skip_init == False:
        #     str += "if (aot_check_init_status(\"{}\", {}))\n".format(name, res_var)
        #     str += "\treturn -1;\n"

        # now that we have initialized the top-level object we need to make sure that
        # all potential pointers inside are initialized too
        # TBD
        # things to consider: pointer fields in structs, members of arrays
        # it seems we need to recursively initialize everything that is not a built-in type
        go_deeper = False
        if cl not in ["builtin", "enum"]:
            # first, let's check if any of the refs in the type is non-builtin
            refs = []
            if self.args.used_types_only and cl == "record":
                refs = type["usedrefs"]
            else:
                refs = type["refs"]

            for t_id in refs:
                tmp_t = self.dbops.typemap[t_id]
                if tmp_t:
                    tmp_t = self.dbops._get_typedef_dst(tmp_t)
                    if tmp_t["class"] != "builtin":
                        go_deeper = True
                        break

            if go_deeper == False:
                if "usedrefs" in type and cl != "pointer" and cl != "enum":
                    for u in type["usedrefs"]:
                        if u != -1:
                            go_deeper = True
                            break

            if go_deeper:
                alloc_tmp = False
                if is_array:
                    # in case of arrays we have to initialize each member separately
                    index = f"i_{level}"
                    # assuming an array has only one ref
                    member_type = type["refs"][0]
                    member_type = self.dbops.typemap[member_type]
                    if (count is None and int(loop_count) > 1) or cl == "const_array" or cl == "incomplete_array":
                        # please note that the loop_count could only be > 0 for an incomplete array if it
                        # was artificially increased in AoT; normally the size of such array in db.json would be 0
                        str += f"for (int {index} = 0; {index} < {loop_count}; {index}++) ""{\n"
                    skip = False
                    if member_type["class"] == "const_array":
                        # const arrays are initialized with enough space already;
                        # we need to pass that information in the recursive call so that
                        # redundant allocations are not made
                        skip = True
                    if cl == "pointer":
                        skip = True

                    tmp_name = ""
                    if (count is None and int(loop_count) > 1) or cl == "const_array" or cl == "incomplete_array":
                        tmp_name = f"{name}[{index}]"
                    else:
                        tmp_name = name
                    if name_change:
                        tmp_name = f"(*{tmp_name})"
                    if self.args.debug_vars_init:
                        logging.info(
                            f"variant E, my type is {type['id']}, loop_count is {loop_count}, cl is {cl}: {tmp_name}")
                    str_tmp, alloc_tmp, brk = self._generate_var_init(f"{tmp_name}",
                                                                      member_type,
                                                                      res_var,
                                                                      pointers[:],
                                                                      level + 1,
                                                                      skip,
                                                                      known_type_names=known_type_names,
                                                                      cast_str=cast_str,
                                                                      new_types=new_types,
                                                                      init_obj=init_obj,
                                                                      fuse=fuse)
                    str += str_tmp
                    if brk:
                        return str, False, brk

                else:
                    # this is not an array
                    # I am not sure at this point if we could have something else
                    # than record or a pointer, but C keeps surprising
                    # pointers are already handled as arrays, so we are left with
                    # records

                    if cl == "record":
                        # remember that we initialized this record
                        _t_id = type["id"]
                        pointers.append(type["id"])
                        if _t_id in self.deps.dup_types:
                            dups = [
                                d for d in self.deps.dup_types[_t_id] if d != _t_id]
                            for d in dups:
                                pointers.append(d)

                        if skip_init:
                            deref_str = "->"
                        else:
                            deref_str = "."
                        # inside the record we will have to find out which of the members
                        # have to be initialized

                        tmp_name = name
                        if name_change:
                            tmp_name = f"(*{tmp_name})"

                        # get the info on bitfields
                        bitfields = {}
                        for i, bitcount in type["bitfields"].items():
                            index = int(i)
                            if ("usedrefs" in type) and (-1 != type["usedrefs"][index]):
                                bitfields[index] = bitcount

                        # since bitfields are initialized by assignment, we have to use struct initializer
                        # this is necessary in order to avoid issues with const pointer members
                        # because the initializer construct zero-initializes all non-specified members,
                        # we initialize all the used bit fields first, then the rest of the struct members
                        str_tmp = ""
                        if len(bitfields) != 0:
                            str_tmp += f"{tmp_name} = ({typename})" + "{"
                            if skip_init and (False == name_change):
                                str_tmp = f"*({typename}*){str_tmp}"

                        for i, bitcount in bitfields.items():
                            field_name = type["refnames"][i]
                            tmp_tid = type["refs"][i]
                            tmp_t = self.dbops._get_typedef_dst(
                                self.dbops.typemap[tmp_tid])
                            # we can generate bitfield init straight away as bitfields are integral types, therefore builtin
                            str_tmp += f".{field_name} = aot_memory_init_bitfield({bitcount}, 1 /* fuzz */, 0), "

                        if len(bitfields) != 0:
                            # remove last comma and space
                            str_tmp = str_tmp[:-2]
                            str_tmp += "};\n"
                            str += str_tmp

                        # if _t_id in self.member_usage_info:
                        #     logging.info(f"Discovered that type {type['str']} is present in the size info data")
                        #     # ok, so we are operating on a record type (a structure) about which we have some additional data
                        #     # the main type of data we have is about the relationship between pointers inside the struct
                        #     # and the corresponding array sizes (which might be constant or represented by other struct members, e.g.buf <-> buf_size)
                        #     # what we have to do is to analyze which data we have, order the init of
                        #     # struct members accordingly and make sure the right size constraints are used during the initialization
                        #     _member_info = self.member_usage_info[_t_id]
                        #     for i in range(len(_member_info)):
                        #         if len(_member_info[i]):
                        #             logging.info(f"We have some data for {type['refnames'][i]} member")

                        members_order, size_constraints = self._get_members_order(
                            type)
                        member_to_name = {}
                        for i in members_order:

                            field_name = type["refnames"][i]

                            # is_typedecl = False
                            # if i in type["decls"]:
                            #    # some of the members are type declarations, so we skip them as there is
                            #    # no way to initialize
                            #    pass
                            if field_name == "__!attribute__":
                                # refnames for attributes can be skipped as they are metadata
                                continue

                            if field_name == "__!anonrecord__" or field_name == "__!recorddecl__" or field_name == "__!anonenum__":
                                # record definitions can be skipped
                                continue

                            is_in_use = self._is_member_in_use(
                                type, tmp_name, i)

                            if is_in_use:
                                tmp_tid = type["refs"][i]
                                obj = init_obj
                                if init_obj is not None:
                                    if init_obj.t_id in init_obj.used_members:
                                        if i in init_obj.used_members[init_obj.t_id]:
                                            if self.args.debug_vars_init:
                                                logging.info(
                                                    f"Member use info detected for {init_obj} member {i}")
                                            obj = init_obj.used_members[init_obj.t_id][i]
                                        # else :
                                        #    logging.info(f"Current init object data found, but member {i} not used")
                                        #    continue
                                    else:
                                        if self.args.debug_vars_init:
                                            logging.info(
                                                f"Could not find member {i} use info in obj tid {init_obj.t_id}")
                                        # continue
                                    # note: currently, if we can't find the member in the current object, we fall back
                                    # to the global member data, which might produce unnecessary inits

                                tmp_t = self.dbops._get_typedef_dst(
                                    self.dbops.typemap[tmp_tid])
                                # if tmp_t["class"] != "builtin":

                                # going deeper
                                if "__!anonrecord__" in tmp_name:
                                    tmp_name = tmp_name.replace(
                                        "__!anonrecord__", "")
                                    deref_str = ""

                                if cast_str != None:
                                    tmp_name = f"(({cast_str}){tmp_name})"
                                    cast_str = None

                                count = None
                                size_member_used = False
                                if len(size_constraints[i]) > 0:
                                    if "size_member" in size_constraints[i]:
                                        _member = size_constraints[i]["size_member"]
                                        if _member in member_to_name:
                                            count = member_to_name[_member]
                                            size_member_used = True
                                    elif "size_member_idx" in size_constraints[i]:
                                        _member = size_constraints[i]["size_member_idx"]
                                        if "max_val" in size_constraints[_member]:
                                            count = size_constraints[_member]["max_val"] + 1
                                    elif "size_value" in size_constraints[i]:
                                        count = size_constraints[i]["size_value"]

                                if i in bitfields:
                                    continue
                                else:
                                    # let's see if we might be dealing with casted pointers
                                    entry, single_init, offset_types = self._get_cast_ptr_data(
                                        type, i)
                                    skip = False
                                    if self.args.debug_vars_init:
                                        logging.info(
                                            f"single_init is {single_init}")

                                    if entry is not None:
                                        # passing skip_init as True in order to prevent
                                        # further initialization of void* as we are handling it here
                                        skip = True
                                    if not single_init:
                                        if self.args.debug_vars_init:
                                            logging.info("variant a")
                                        member_to_name[i] = f"{tmp_name}{deref_str}{field_name}"
                                        str_tmp, alloc_tmp, brk = self._generate_var_init(f"{tmp_name}{deref_str}{field_name}",
                                                                                     tmp_t,
                                                                                     res_var,
                                                                                     pointers[:],
                                                                                     level,
                                                                                     skip_init=skip,
                                                                                     known_type_names=known_type_names,
                                                                                     cast_str=cast_str,
                                                                                     new_types=new_types,
                                                                                     init_obj=obj,
                                                                                     fuse=fuse,
                                                                                     count=count)
                                        if size_member_used:
                                            str += "// smart init: using one struct member as a size of another\n"
                                        str += str_tmp
                                        str += self._generate_constraints_check(
                                            f"{tmp_name}{deref_str}{field_name}", size_constraints[i])
                                        if brk:
                                            return str, False,brk

                                    if entry is not None:
                                        if self.args.debug_vars_init:
                                            logging.info("variant b")
                                        variant = ""
                                        variant_num = 1
                                        for dst_tid in entry[i]:
                                            dst_t = self.dbops.typemap[dst_tid]
                                            typename = self.codegen._get_typename_from_type(
                                                dst_t)

                                            active_type = self.dbops.typemap[self.dbops._get_real_type(
                                                tmp_tid)]
                                            active_type = self.dbops._get_typedef_dst(
                                                active_type)
                                            casted_type = self.dbops.typemap[self.dbops._get_real_type(
                                                dst_tid)]
                                            casted_type = self.dbops._get_typedef_dst(
                                                casted_type)
                                            struct_types = [
                                                "record", "record_forward"]
                                            if active_type["class"] in struct_types and casted_type["class"] not in struct_types:
                                                if self.args.debug_vars_init:
                                                    logging.info(
                                                        "will not consider cast of structural type to non-structural type")
                                                continue

                                            if new_types != None:
                                                new_types.add(dst_tid)

                                            brk = False
                                            if not single_init and self.args.single_init_only:
                                                str_tmp = ""                                                
                                            else:
                                                # generate an alternative init for each of the detected casts
                                                str_tmp, alloc_tmp, brk = self._generate_var_init(f"{tmp_name}{deref_str}{field_name}",
                                                                                            dst_t,
                                                                                            res_var,
                                                                                            pointers[:],
                                                                                            level,
                                                                                            False,
                                                                                            known_type_names=known_type_names,
                                                                                            cast_str=typename,
                                                                                            new_types=new_types,
                                                                                            init_obj=obj,
                                                                                            fuse=fuse,
                                                                                            count=count)
                                                if not single_init:
                                                    variant = f"variant {variant_num}"
                                                    variant_num += 1
                                                else:
                                                    member_to_name[i] = f"{tmp_name}{deref_str}{field_name}"
                                                if size_member_used:
                                                    str_tmp = f"// smart init: using one struct member as a size of another\n{str_tmp}"
                                                str_tmp += self._generate_constraints_check(
                                                    f"{tmp_name}{deref_str}{field_name}", size_constraints[i])

                                                str_tmp = f"\n// smart init (b) {variant}: we've found that this pointer var is casted to another type: {typename}\n{str_tmp}"
                                            # logging.info(str_tmp)
                                            if not single_init:
                                                str_tmp = str_tmp.replace(
                                                    "\n", "\n//")
                                                if str_tmp.endswith("//"):
                                                    str_tmp = str_tmp[:-2]
                                            str += str_tmp
                                            if brk:
                                                return str, False, brk

                            # else:
                            #    str += f"// {name}{deref_str}{field_name} never used -> skipping init\n"
                    else:
                        logging.error(
                            f"Unexpected deep var class {cl} for {name}")
                        # sys.exit(1)
            else:
                str += f"// didn't find any deeper use of {name}\n"

        prefix = ""
        if level != 0:
            for i in range(level):
                prefix += "  "
            str = prefix + str
            str = str.replace("\n", f"\n{prefix}")
            str = str[:-(2*level)]

        if is_array and go_deeper and ((count is None and loop_count > 1) or cl == "const_array" or cl == "incomplete_array"):
            str += f"{prefix}""}\n"  # close the for loop

        return str, alloc, False

    # -------------------------------------------------------------------------

    # @belongs: init
    @staticmethod
    def _sort_order(a, b):
        if a["id"] < b["id"]:
            return -1
        elif a["id"] > b["id"]:
            return 1
        else:
            return 0

    # @belongs: init
    def _collect_derefs_trace(self, f_id, functions):
        # we process functions in DFS mode - starting from f_id and within the scope of the 'functions' set
        # this is supposed to resemble normal sequential execution of a program
        # within each of the functions we need to establish the right order of derefs and function calls
        # since function calls can preceed certain derefs and we operate in a DFS-like way

        DEREF = "deref"
        CALL = "call"
        derefs_trace = []

        f = self.dbops.fnidmap[f_id]
        if f is None:
            return derefs_trace
        self.debug_derefs(f"Collecting derefs for function {f['name']}")
        # first we need to establish a local order of funcs and derefs
        ordered = []
        ord_to_deref = {}
        for d in f["derefs"]:
            ords = []
            if isinstance(d["ord"], list):
                ords = d["ord"]
            else:  # ord is just a number
                ords.append(d["ord"])
            for o in ords:
                ordered.append({"type": DEREF, "id": o, "obj": d})
                self.debug_derefs(f"Appending deref {d}")
                if o in ord_to_deref:
                    logging.error("Didn't expect ord to reappear")
                ord_to_deref[o] = d
        for i in range(len(f["call_info"])):
            c = f["call_info"][i]
            call_id = f["calls"][i]
            if call_id in functions:
                ords = []
                if isinstance(c["ord"], list):
                    ords = c["ord"]
                else:  # ord is just a number
                    ords.append(c["ord"])
                for o in ords:
                    # note: if the deref happens several times in the trace, it will have several entries
                    # in the ord list -> one per each occurrence
                    # below we duplicate the occurrences according to their order in the trace
                    ordered.append({"type": CALL, "id": o, "obj": call_id})
                    self.debug_derefs(f"Appending call {call_id}, ord {o}")
        ordered = sorted(ordered, key=functools.cmp_to_key(Init._sort_order))

        # ideally we would like to have member dereferences go _before_ casts so that we can
        # match them accordingly
        # in db.json casts can contain member dereferences which are located _after_ the cast in the derefs trace
        # the pass below is meant to rectify that: put member derefs before the associated casts
        self.debug_derefs("REORDERING TRACE")
        index = 0
        while index < len(ordered):
            item = ordered[index]
            if item["type"] == CALL:
                index += 1
                continue
            deref = item["obj"]
            deref_id = int(item["id"])  # id is the deref's order -> see above
            cast_data = self._get_cast_from_deref(deref, f)
            inserts_num = 0
            if cast_data is not None:
                logging.debug("Cast data is not none")
                for t_id in cast_data:
                    for member in cast_data[t_id]:
                        self.debug_derefs(
                            f"MEMBER IS {member} deref is {deref}")
                        if member != Init.CAST_PTR_NO_MEMBER:
                            # first, we have to find the deref the cast refers to:
                            for oref in deref["offsetrefs"]:
                                if "cast" in oref and oref["kind"] == "member":
                                    dst_deref_id = oref["id"]
                                    # we have the id of the deref that contains the member access
                                    # we now need to find it in the trace
                                    dst_deref = f["derefs"][dst_deref_id]

                                    ords = dst_deref["ord"]
                                    # find the instance with a smallest ord number larger than the current
                                    # deref id
                                    for o in ords:
                                        found = False
                                        if o > deref_id:
                                            logging.debug("Processing ords...")
                                            # found it!
                                            # we have the order number, let's find the associated
                                            # deref object
                                            for i in range(len(ordered)):
                                                if ordered[i]["id"] == o:
                                                    # found the associated deref
                                                    # now, let's put that deref just before the currently
                                                    # processed cast
                                                    diff = i - index
                                                    self.debug_derefs(
                                                        f"Moving item {ordered[i]} to index {index} size is {len(ordered)} diff {diff}")
                                                    ordered[i]["id"] -= diff
                                                    ordered.insert(
                                                        index, ordered[i])
                                                    deref_id += 1
                                                    inserts_num += 1
                                                    # and remove the current
                                                    # +1 since we inserted one element before
                                                    del ordered[i + 1]
                                                    # we have to update the ids of items that go after the inserted one
                                                    # for j in range(index + 1, len(ordered)):
                                                    #     ordered[j]["id"] += 1
                                                    self.debug_derefs(
                                                        f"size is {len(ordered)}")
                                                    found = True
                                                    break

                                            break
                                        if found:
                                            break
            index += inserts_num
            index += 1
        self.debug_derefs("REORDERING CALL REFS")
        # similarly, when there is a cast happening as a result of function return value being modified
        # e.g. B* b = foo() // a* foo()
        # the call happens after the cast in db.json's order -> we want the call to happen first
        index = 0
        while index < len(ordered):
            item = ordered[index]

            if item["type"] == CALL:
                index += 1
                continue

            deref = item["obj"]
            deref_id = int(item["id"])  # id is the deref's order -> see above
            self.debug_derefs(f"processing deref {deref}")

            inserts_num = 0
            if self._get_callref_from_deref(deref):
                self.debug_derefs("callref detected")
                for oref in deref["offsetrefs"]:
                    if oref["kind"] == "callref":
                        # get the related call order
                        ords = f["call_info"][oref["id"]]["ord"]
                        if not isinstance(ords, list):
                            ords = [ords]

                        for o in ords:
                            found = False
                            if o > deref_id:
                                self.debug_derefs("processing ords...")
                                # seems like we've found a call with order
                                # greater than our cast -> let's move it
                                for i in range(len(ordered)):
                                    if ordered[i]["id"] == o:
                                        # that is our function call
                                        diff = i - index
                                        self.debug_derefs(
                                            f"Moving item {ordered[i]} from index {i} to index {index} size is {len(ordered)} diff {diff}")
                                        ordered[i]["id"] -= diff
                                        ordered.insert(index, ordered[i])
                                        deref_id += 1
                                        inserts_num += 1
                                        del ordered[i + 1]
                                        # we have to update the ids of items that go after the inserted one
                                        # for j in range(index + 1, len(ordered)):
                                        #     ordered[j]["id"] += 1
                                        self.debug_derefs(
                                            f"size is {len(ordered)}")
                                        found = True

                                break
                            if found:
                                break

                        # cool, we have moved the call to it's right place,
                        # but we still have to handle the call's params: most likely
                        # as their related call they are also located past the cast deref
                        # first let's get their ids:
                        args = f["call_info"][oref["id"]]["args"]
                        # args is a list of ids in our derefs table

                        for _deref_id in args:
                            self.debug_derefs("handling args")
                            deref_obj = f["derefs"][_deref_id]
                            ords = deref_obj["ord"]

                            for o in ords:
                                found = False
                                if o > deref_id:
                                    for i in range(len(ordered)):
                                        if ordered[i]["id"] == o:
                                            diff = i - index
                                            self.debug_derefs(
                                                f"Moving item {ordered[i]} from index {i} to index {index} size is {len(ordered)} diff {diff}")
                                            ordered[i]["id"] -= diff
                                            ordered.insert(index, ordered[i])
                                            deref_id += 1
                                            inserts_num += 1
                                            del ordered[i + 1]
                                            # # we have to update the ids of the items that go after the inserted one
                                            # for j in range(index + 1, len(ordered)):
                                            #     ordered[j]["id"] += 1
                                            self.debug_derefs(
                                                f"size is {len(ordered)}")
                                            found = True

                                            # once we moved params we also need to move the associated derefs
                                            if ordered[index]["type"] == DEREF:
                                                param_deref = ordered[index]["obj"]
                                                for _oref in param_deref["offsetrefs"]:
                                                    if _oref["kind"] == "member":
                                                        member_deref = f["derefs"][_oref["id"]]
                                                        member_ords = member_deref["ord"]
                                                        for _o in member_ords:
                                                            if _o > deref_id:
                                                                for _i in range(len(ordered)):
                                                                    if ordered[_i]["id"] == _o:
                                                                        if ordered[_i]["type"] == DEREF and ordered[_i]["obj"]["kind"] == "member":
                                                                            diff = _i - index
                                                                            self.debug_derefs(
                                                                                f"Moving member arg {ordered[_i]} from index {_i} to index {index} size is {len(ordered)} diff {diff}")
                                                                            ordered[_i]["id"] -= diff
                                                                            ordered.insert(
                                                                                index, ordered[_i])
                                                                            deref_id += 1
                                                                            inserts_num += 1
                                                                            del ordered[_i + 1]
                                                                            self.debug_derefs(
                                                                                f"size is {len(ordered)}")
                                                    elif _oref["kind"] == "array":
                                                        array_deref = f["derefs"][_oref["id"]]
                                                        if array_deref["kind"] == "array":
                                                            member_deref = None
                                                            for __oref in array_deref["offsetrefs"]:
                                                                if __oref["kind"] == "member":
                                                                    member_deref = f["derefs"][__oref["id"]]
                                                                    break
                                                            if member_deref is not None:
                                                                member_ords = member_deref["ord"]
                                                                for _o in member_ords:
                                                                    if _o > deref_id:
                                                                        for _i in range(len(ordered)):
                                                                            if ordered[_i]["id"] == _o:
                                                                                if ordered[_i]["type"] == DEREF and ordered[_i]["obj"]["kind"] == "member":
                                                                                    diff = _i - index
                                                                                    self.debug_derefs(
                                                                                        f"Moving member arg {ordered[_i]} from index {_i} to index {index} size is {len(ordered)} diff {diff}")
                                                                                    ordered[_i]["id"] -= diff
                                                                                    ordered.insert(
                                                                                        index, ordered[_i])
                                                                                    deref_id += 1
                                                                                    inserts_num += 1
                                                                                    del ordered[_i + 1]
                                                                                    self.debug_derefs(
                                                                                        f"size is {len(ordered)}")

                                if found:
                                    break

            # cast_data = self._get_cast_from_deref(deref, f)
            # inserts_num = 0
            # if cast_data is not None:
            #     logging.info("CAST DATA IS NOT NONE")
            #     for t_id in cast_data:
            #         for member in cast_data[t_id]:
            #             if member == Generator.CAST_PTR_NO_MEMBER:
            #                 for oref in deref["offsetrefs"]:
            #                     if "cast" in oref and oref["kind"] == "callref":
            #                         # get the related call order
            #                         ords = f["call_info"][oref["id"]]["ord"]
            #                         if not isinstance(ords, list):
            #                             ords = [ ords ]

            #                         for o in ords:
            #                             found = False
            #                             if o > deref_id:
            #                                 logging.info("processing ords...")
            #                                 # seems like we've found a call with order
            #                                 # greater than our cast -> let's move it
            #                                 for i in range(len(ordered)):
            #                                     if ordered[i]["id"] == o:
            #                                         # that is our function call
            #                                         diff = i - index
            #                                         logging.info(f"Moving item {ordered[i]} from index {i} to index {index} size is {len(ordered)} diff {diff}")
            #                                         ordered[i]["id"] -= diff
            #                                         ordered.insert(index, ordered[i])
            #                                         deref_id += 1
            #                                         inserts_num += 1
            #                                         del ordered[i + 1]
            #                                         # we have to update the ids of items that go after the inserted one
            #                                         # for j in range(index + 1, len(ordered)):
            #                                         #     ordered[j]["id"] += 1
            #                                         logging.info(f"size is {len(ordered)}")
            #                                         found = True

            #                                 break
            #                             if found:
            #                                 break

            #                         # cool, we have moved the call to it's right place,
            #                         # but we still have to handle the call's params: most likely
            #                         # as their related call they are also located past the cast deref
            #                         # first let's get their ids:
            #                         args = f["call_info"][oref["id"]]["args"]
            #                         # args is a list of ids in our derefs table

            #                         for _deref_id in args:
            #                             logging.info("handling args")
            #                             deref_obj = f["derefs"][_deref_id]
            #                             ords = deref_obj["ord"]

            #                             for o in ords:
            #                                 found = False
            #                                 if o > deref_id:
            #                                     for i in range(len(ordered)):
            #                                         if ordered[i]["id"] == o:
            #                                             diff = i - index
            #                                             logging.info(f"Moving item {ordered[i]} from index {i} to index {index} size is {len(ordered)} diff {diff}")
            #                                             ordered[i]["id"] -= diff
            #                                             ordered.insert(index, ordered[i])
            #                                             deref_id += 1
            #                                             inserts_num += 1
            #                                             del ordered[i + 1]
            #                                             # # we have to update the ids of the items that go after the inserted one
            #                                             # for j in range(index + 1, len(ordered)):
            #                                             #     ordered[j]["id"] += 1
            #                                             logging.info(f"size is {len(ordered)}")
            #                                             found = True
            #                                     break
            #                                 if found:
            #                                     break
            index += inserts_num
            index += 1
        self.debug_derefs("PROCESSING MEMBERS")
        # one more reordering pass: if we have an offsetref item with kind member, make sure that
        # it goes before the cotaining dereference
        index = 0
        while index < len(ordered):
            item = ordered[index]

            if item["type"] == CALL:
                index += 1
                continue

            deref = item["obj"]
            deref_id = int(item["id"])
            if "offsetrefs" in deref:
                for oref in deref["offsetrefs"]:
                    if oref["kind"] == "member":
                        # we have found an offsetref that relates to member
                        dst_id = oref["id"]
                        # getting the deref the member oref relates to
                        dst_deref = f["derefs"][dst_id]

                        # now we need to make sure that dst_deref is located in the trace
                        # before this deref

                        ords = dst_deref["ord"]
                        for o in ords:
                            found = False
                            if o > deref_id:
                                for i in range(len(ordered)):
                                    if ordered[i]["id"] == o:
                                        diff = i - index
                                        self.debug_derefs(
                                            f"Moving item {ordered[i]} from index {i} to index {index} size is {len(ordered)} diff {diff}")
                                        ordered[i]["id"] -= diff
                                        ordered.insert(index, ordered[i])
                                        deref_id += 1
                                        inserts_num += 1
                                        del ordered[i + 1]
                                        found = True
                                break
                            if found:
                                break
            index += inserts_num
            index += 1

        # logging.info("PROCESSING OFFSETOFFS")
        # # one more reordering pass: if we have an offsetref item with kind offsetof, make sure that
        # # it goes before the cotaining dereference
        # index = 0
        # while index < len(ordered):
        #     item = ordered[index]

        #     if item["type"] == CALL:
        #         index += 1
        #         continue

        #     deref = item["obj"]
        #     deref_id = int(item["id"])
        #     if "offsetrefs" in deref:
        #         for oref in deref["offsetrefs"]:
        #             if oref["kind"] == "offsetof":
        #                 # we have found an offsetref that relates to member
        #                 dst_id = oref["id"]
        #                 # getting the deref the member oref relates to
        #                 dst_deref = f["derefs"][dst_id]

        #                 # now we need to make sure that dst_deref is located in the trace
        #                 # before this deref

        #                 ords = dst_deref["ord"]
        #                 for o in ords:
        #                     found = False
        #                     if o > deref_id:
        #                         for i  in range(len(ordered)):
        #                             if ordered[i]["id"] == o:
        #                                 diff = i - index
        #                                 logging.info(f"Moving item {ordered[i]} from index {i} to index {index} size is {len(ordered)} diff {diff}")
        #                                 ordered[i]["id"] -= diff
        #                                 ordered.insert(index, ordered[i])
        #                                 deref_id += 1
        #                                 inserts_num += 1
        #                                 del ordered[i + 1]
        #                                 found = True
        #                         break
        #                     if found:
        #                         break
        #     index += inserts_num
        #     index += 1

        logging.debug(f"ordered trace is {ordered}")

        for i in range(len(ordered)):
            item = ordered[i]
            if item["type"] == DEREF:
                derefs_trace.append((item["obj"], f))
            elif item["type"] == CALL:
                _f_id = item["obj"]
                _functions = set(functions)
                if f_id in _functions:
                    # mark that we processed the current function already
                    _functions.remove(f_id)
                if _f_id in self.trace_cache:
                    derefs_trace += self.trace_cache[_f_id]
                else:
                    ftrace = self._collect_derefs_trace(_f_id, _functions)
                    self.trace_cache[_f_id] = ftrace
                    derefs_trace += ftrace

        logging.info(f"Collected trace for function {f['name']} is")
        for obj, f in derefs_trace:
            self.debug_derefs(f"{f['id']} : {obj}")

        return derefs_trace

    # -------------------------------------------------------------------------

    # @belongs: init
    def debug_derefs(self, msg):
        if self.args.debug_derefs:
            logging.info(msg)

    # @belongs: init
    def _match_obj_to_type(self, t_id, objects, adjust_recfwd=True):
        self.debug_derefs(f"matching object to type {t_id}")
        matched_objs = []

        # return matched_objs
        for obj in objects:

            _active_tid = obj.t_id
            _t_id = t_id

            if obj.is_pointer:
                _active_tid = self.dbops._get_real_type(_active_tid)
                _t_id = self.dbops._get_real_type(t_id)

            _active_type = self.dbops.typemap[_active_tid]
            _active_type_recfw = False
            if _active_type["class"] == "record_forward":
                _active_type_recfw = True

            base_type = self.dbops.typemap[_t_id]
            base_type_recfwd = False
            if base_type["class"] == "record_forward":
                base_type_recfwd = True

            if t_id == obj.t_id or _t_id == _active_tid:
                matched_objs.append(obj)
            elif t_id in self.deps.dup_types and obj.t_id in self.deps.dup_types[t_id]:
                matched_objs.append(obj)
            elif _t_id in self.deps.dup_types and _active_tid in self.deps.dup_types[_t_id]:
                matched_objs.append(obj)
            elif (base_type_recfwd or _active_type_recfw) and (base_type["str"] == _active_type["str"]):
                # we assume that we came across a record forward
                matched_objs.append(obj)
            # we want to avoid matching void* in historic casts
            elif not self._is_void_ptr(base_type) and base_type["str"] != "void":
                prev_cast_found = False

                for _prev_t_id, _original_tid, _is_pointer in obj.cast_types:
                    self.debug_derefs(
                        f"Checking cast history {_prev_t_id} {_original_tid} {_is_pointer}")
                    if _t_id == _prev_t_id or _t_id == _original_tid or t_id == _prev_t_id or t_id == _original_tid:
                        prev_cast_found = True
                        break
                    _prev_type = self.dbops.typemap[_prev_t_id]
                    _original_type = self.dbops.typemap[_original_tid]
                    _prev_type_recfw = False
                    _original_type_recfwd = False
                    if _prev_type["class"] == "record_forward":
                        _prev_type_recfw = True
                    if _original_type["class"] == "record_forward":
                        _original_type_recfwd = True
                    if (base_type_recfwd or _prev_type_recfw or _original_type_recfwd) and (base_type["str"] == _prev_type["str"] or base_type["str"] == _original_type["str"]):
                        prev_cast_found = True
                        break

                if prev_cast_found:
                    matched_objs.append(obj)

        if adjust_recfwd and len(matched_objs) == 1:
            # we have exactly one match
            obj = matched_objs[0]
            _t_id = t_id
            _obj_id = obj.t_id
            if obj.is_pointer:
                _t_id = self.dbops._get_real_type(t_id)
                _obj_id = self.dbops._get_real_type(obj.t_id)
            base_type = self.dbops.typemap[_t_id]
            obj_type = self.dbops.typemap[_obj_id]
            if base_type["class"] == "record" and obj_type["class"] == "record_forward":
                # We initially created this object as a record forward type but now
                # we found the corresponding record for it -> let's update the data in the object
                self.debug_derefs(
                    f"Updating object type from record fwd to record {obj.t_id} -> {t_id}")
                for k in obj.used_members.keys():
                    if k == obj.t_id:
                        obj.used_members[t_id] = obj.used_members[k]
                obj.t_id = t_id
                obj.original_tid = t_id

        return matched_objs

    # starting from the function f_id, collect a trace of all derefs in a DFS-like manner
    # the collected trace is then used to reason about possible casts and uses of types
    # f_id: id of a function we start the trace analysis from
    # functions: a set of functions within which we are processing the trace
    # by default we will process all argument types of the specified function
    # tids: an optional list of types we will be processing (this can be useful if we wish
    # to include global types in the analysis)
    # @belongs: init
    def _parse_derefs_trace(self, f_id, functions, tids=None):
        # before we can start reasoning we have to collect the trace

        trace = self._collect_derefs_trace(f_id, functions)

        # we will now perform an analysis of the collected derefs trace for each of
        # the function parameter types

        # first, let's get the types
        f = self.dbops.fnidmap[f_id]
        arg_tids = f["types"][1:]  # types[0] is a return type of the function
        self.debug_derefs(
            f"processing derefs for function {f['name']}, trace size is {len(trace)}")
        if tids != None:
            for t_id in tids:
                arg_tids.append(t_id)

        active_object = None
        typeuse_objects = []
        ret_val = []

        base_obj = None
        for t_id in arg_tids:
            # for a given type we are interested in all casts and offsetof uses
            # what we want to try to learn here is whether the type is used as such or
            # is casted to another type or is a member of another type (offsetof operator)

            # let's create the first TypeUse for the t_id
            base_obj = TypeUse(self.dbops._get_real_type(
                t_id), t_id, self.dbops.typemap[t_id]["class"] == "pointer")
            typeuse_objects = []
            typeuse_objects.append(base_obj)
            base_obj.name = self.codegen._get_typename_from_type(
                self.dbops.typemap[base_obj.t_id])
            logging.info(f"Generated TypeUse {base_obj}")

            active_object = base_obj

            for (deref, f) in trace:
                self.debug_derefs(f"Deref is {deref}")

                cast_data = self._get_cast_from_deref(deref, f)
                if cast_data is not None:
                    self.debug_derefs(f"cast data is {cast_data}")
                    # current_tid = active_object.t_id
                    for current_tid in cast_data:  # we only check if the current object was casted
                        for member in cast_data[current_tid]:
                            _current_tid = current_tid
                            _active_tid = active_object.t_id
                            if active_object.is_pointer:
                                _current_tid = self.dbops._get_real_type(
                                    _current_tid)

                            if member == Init.CAST_PTR_NO_MEMBER:
                                if current_tid != active_object.t_id and _current_tid != _active_tid:
                                    if current_tid in self.deps.dup_types and active_object.t_id in self.deps.dup_types[current_tid]:
                                        self.debug_derefs("dup")
                                        pass
                                    elif _current_tid in self.deps.dup_types and _active_tid in self.deps.dup_types[_current_tid]:
                                        self.debug_derefs("dup")
                                        pass
                                    else:
                                        other_objs = self._match_obj_to_type(
                                            current_tid, typeuse_objects)
                                        if len(other_objs) == 1:
                                            self.debug_derefs(
                                                f"Active object change detected: from {active_object.id} to {other_objs[0].id}")
                                            active_object = other_objs[0]
                                        else:
                                            self.debug_derefs(
                                                f"Active object id is {active_object.t_id} {_active_tid}, and id is {current_tid} {_current_tid}")
                                            continue
                                # the type is casted directly, i.e. without member dereference
                                casted_tid = cast_data[current_tid][member][0]

                                if active_object.t_id != casted_tid:
                                    active_type = self.dbops.typemap[self.dbops._get_real_type(
                                        active_object.t_id)]
                                    active_type = self.dbops._get_typedef_dst(
                                        active_type)
                                    casted_type = self.dbops.typemap[self.dbops._get_real_type(
                                        casted_tid)]
                                    casted_type = self.dbops._get_typedef_dst(
                                        casted_type)
                                    struct_types = ["record", "record_forward"]
                                    if active_type["class"] in struct_types and casted_type["class"] not in struct_types:
                                        self.debug_derefs(
                                            "skipping cast of structural type to non-structural type")
                                    else:
                                        self.debug_derefs(
                                            "Adding to casted types")
                                        active_object.cast_types.append(
                                            (active_object.t_id, active_object.original_tid, active_object.is_pointer))
                                        # update the active type of the object
                                        active_object.t_id = casted_tid
                                        active_object.original_tid = casted_tid
                                        if self.dbops.typemap[casted_tid]["class"] == "pointer":
                                            active_object.is_pointer = True
                                        else:
                                            active_object.is_pointer = False
                                        active_object.name = self.codegen._get_typename_from_type(
                                            self.dbops.typemap[active_object.t_id])
                                else:
                                    self.debug_derefs(
                                        "skipping cast due to type mismatch")

                            else:
                                # first we take the member of the type and then we cast
                                # when members are involved in casts, cast expression happens before member
                                # expression
                                # this is not the order we would like to have, so we need to process that
                                # case separately
                                # The cast type doesn't refer to the the current object type but to it's
                                # member that is retrieved via the member expression (which is comming
                                # afterwards in the trace)
                                # we handle this in the _collect_derefs_trace function in which we
                                # reorder the trace such that member expressions come before casts
                                # if the reordering works correctly we should see that the type of
                                # an active object is the same as the type of the casted member
                                src_type = self.dbops.typemap[current_tid]
                                member_tid = src_type["refs"][member]
                                _member_tid = member_tid
                                if active_object.is_pointer:
                                    _member_tid = self.dbops._get_real_type(
                                        member_tid)

                                if active_object.t_id == member_tid or _active_tid == _member_tid:
                                    casted_tid = cast_data[current_tid][member][0]
                                    active_type = self.dbops.typemap[self.dbops._get_real_type(
                                        active_object.t_id)]
                                    active_type = self.dbops._get_typedef_dst(
                                        active_type)
                                    casted_type = self.dbops.typemap[self.dbops._get_real_type(
                                        casted_tid)]
                                    casted_type = self.dbops._get_typedef_dst(
                                        casted_type)
                                    struct_types = ["record", "record_forward"]
                                    if active_type["class"] in struct_types and casted_type["class"] not in struct_types:
                                        self.debug_derefs(
                                            "skipping cast of structural type to non-structural type")
                                    else:
                                        self.debug_derefs("adding to casts")
                                        active_object.cast_types.append(
                                            (active_object.t_id, active_object.original_tid, active_object.is_pointer))
                                        active_object.t_id = casted_tid
                                        active_object.original_tid = casted_tid
                                        if self.dbops.typemap[casted_tid]["class"] == "pointer":
                                            active_object.is_pointer = True
                                        else:
                                            active_object.is_pointer = False
                                        active_object.name = self.codegen._get_typename_from_type(
                                            self.dbops.typemap[active_object.t_id])
                                else:
                                    self.debug_derefs(
                                        "skipping cast due to type mismatch")
                else:
                    offsetof_data = self._get_offsetof_from_deref(deref)
                    if offsetof_data is not None:
                        # first, let's check if we don't have the containing TypeUse object already
                        self.debug_derefs(f"deref is {deref}")

                        member_no = deref["member"][-1]
                        # type[0] is the dst type
                        base_tid = self.dbops.typemap[deref["type"]
                                                      [-1]]["refs"][member_no]
                        dst_tid = deref["type"][0]

                        _base_tid = base_tid
                        _active_tid = active_object.t_id
                        if active_object.is_pointer:
                            _active_tid = self.dbops._get_real_type(
                                _active_tid)

                        if base_tid != active_object.t_id and _base_tid != _active_tid:
                            if base_tid in self.deps.dup_types and active_object.t_id in self.deps.dup_types[base_tid]:
                                self.debug_derefs("dup")
                                pass
                            elif _base_tid in self.deps.dup_types and _active_tid in self.deps.dup_types[_base_tid]:
                                self.debug_derefs("dup")
                                pass
                            else:
                                other_objs = self._match_obj_to_type(
                                    base_tid, typeuse_objects)
                                if len(other_objs) == 1:
                                    self.debug_derefs(
                                        f"Active object change detected: from {active_object.id} to {other_objs[0].id}")
                                    active_object = other_objs[0]
                                else:
                                    continue
                        found = False
                        for types, members, obj in active_object.offsetof_types:
                            if types == deref["type"] and members == deref["member"]:
                                # we already have that object
                                self.debug_derefs(
                                    f"Active object changed from {active_object.id} to {obj.id}")
                                active_object = obj
                                found = True
                                break
                        if not found:
                            # we need to allocate new TypeUse object for the destination
                            # type of the offsetof operator
                            self.debug_derefs("Creating new offsetof object")
                            # we a assume that we use offsetof to
                            new_object = TypeUse(
                                self.dbops._get_real_type(dst_tid), dst_tid, True)
                            # get a pointer
                            typeuse_objects.append(new_object)
                            new_object.name = self.codegen._get_typename_from_type(
                                self.dbops.typemap[new_object.t_id])
                            self.debug_derefs(
                                f"Generated TypeUse {new_object}")
                            active_object.offsetof_types.append(
                                (deref["type"], deref["member"], new_object))
                            new_object.contained_types.append(
                                (deref["type"], deref["member"], active_object))
                            # change active object
                            self.debug_derefs(
                                f"Active object changed from {active_object.id} to {new_object.id}")
                            active_object = new_object
                        else:
                            self.debug_derefs("Using existing offsetof object")
                    else:
                        member_data, access_order = self._get_member_access_from_deref(
                            deref)

                        if member_data:
                            self.debug_derefs("Member access is not none")
                        else:
                            self.debug_derefs("Member access is none")
                        if member_data is not None:

                            # check if we refer to the current active object !
                            first_tid = member_data[access_order[0]]["id"]

                            _first_tid = first_tid
                            _active_tid = active_object.t_id
                            if active_object.is_pointer:
                                _first_tid = self.dbops._get_real_type(
                                    _first_tid)
                                _active_tid = self.dbops._get_real_type(
                                    _active_tid)
                            if first_tid != active_object.t_id and _first_tid != _active_tid:
                                if first_tid in self.deps.dup_types and active_object.t_id in self.deps.dup_types[first_tid]:
                                    self.debug_derefs("dup")
                                    pass
                                elif _first_tid in self.deps.dup_types and _active_tid in self.deps.dup_types[_first_tid]:
                                    self.debug_derefs("dup")
                                    pass
                                else:
                                    prev_cast_found = False
                                    for _t_id, _original_tid, _is_pointer in active_object.cast_types:
                                        self.debug_derefs(
                                            f"Checking cast history {_t_id} {_original_tid} {_is_pointer}")
                                        if _first_tid == _t_id or _first_tid == _original_tid or first_tid == _t_id or first_tid == _original_tid:
                                            prev_cast_found = True
                                            break
                                    if prev_cast_found:
                                        self.debug_derefs(
                                            "Phew, we've found the previous cast that matches the type id")
                                    else:
                                        # one last check would be to see if there is a single type match among the active
                                        # objects -> this trick is aimed at helping in a situation where the sequence of
                                        # dereferences is non-monotonic - e.g. we get a pointer, store it in a variable
                                        # then we use another pointer and get back to the first one;
                                        # a heavier approach to this problem would be to perform some sort of data flow or variable
                                        # name tracking; what we do here is to assume that if we have a single matching type, it's probably
                                        # one of the objects we already created

                                        other_objs = self._match_obj_to_type(
                                            first_tid, typeuse_objects)
                                        if len(other_objs) == 1:
                                            self.debug_derefs(
                                                f"Active object change detected: from {active_object.id} to {other_objs[0].id}")
                                            active_object = other_objs[0]

                                        else:
                                            self.debug_derefs(
                                                f"Active object id is {active_object.t_id} {_active_tid}, and id is {first_tid} {_first_tid}")
                                            continue
                            self.debug_derefs(
                                f"access order is {access_order}")
                            for t_id in access_order:
                                t = member_data[t_id]
                                for i in range(len(t["usedrefs"])):
                                    member_tid = t["usedrefs"][i]
                                    if member_tid != -1:
                                        member_no = i
                                        active_tid = active_object.t_id
                                        # check if the member is already in our used members data:
                                        if active_tid in active_object.used_members and member_no in active_object.used_members[active_tid]:
                                            # yes -> we pick the existing object
                                            self.debug_derefs(
                                                f"Active object changed from {active_object.id} to {active_object.used_members[active_tid][member_no].id}")
                                            active_object = active_object.used_members[active_tid][member_no]
                                            self.debug_derefs(
                                                "Member detected in used members")
                                        else:
                                            # check if the member is present in the contained types:
                                            # if yes, use the existing object
                                            offsetof_found = False
                                            for types, members, obj in active_object.contained_types:
                                                if types[-1] == t_id and member_no == members[-1]:
                                                    self.debug_derefs(
                                                        "This member was used in a prior offsetof")
                                                    if active_tid not in active_object.used_members:
                                                        active_object.used_members[active_tid] = {
                                                        }
                                                    active_object.used_members[active_tid][member_no] = obj
                                                    self.debug_derefs(
                                                        f"Active object changed from {active_object.id} to {obj.id}")
                                                    active_object = obj
                                                    offsetof_found = True
                                            if offsetof_found:
                                                continue
                                            self.debug_derefs(
                                                "Creating new member")
                                            # no -> we create a new object
                                            new_object = TypeUse(self.dbops._get_real_type(
                                                member_tid), member_tid, self.dbops.typemap[member_tid]["class"] == "pointer")
                                            typeuse_objects.append(new_object)
                                            new_object.name = self.codegen._get_typename_from_type(
                                                self.dbops.typemap[new_object.t_id])
                                            self.debug_derefs(
                                                f"Generated TypeUse {new_object}")

                                            active_type = self.dbops.typemap[active_tid]
                                            obj_type = self.dbops.typemap[t_id]
                                            if active_type["class"] == "record_forward" and active_tid != t_id and obj_type["class"] == "record":
                                                self.debug_derefs(
                                                    f"Updating object type from record fwd to record {active_tid} -> {t_id}")
                                                for k in active_object.used_members.keys():
                                                    if k == obj.t_id:
                                                        active_object.used_members[t_id] = active_object.used_members[k]
                                                active_object.t_id = t_id
                                                active_object.original_tid = t_id

                                            # take a note that the member is used
                                            if active_object.t_id not in active_object.used_members:
                                                active_object.used_members[active_object.t_id] = {
                                                }
                                            active_object.used_members[active_object.t_id][member_no] = new_object
                                            # update active object
                                            self.debug_derefs(
                                                f"Active object changed from {active_object.id} to {new_object.id}")
                                            active_object = new_object
            ret_val.append((t_id, base_obj))

        return ret_val

    # -------------------------------------------------------------------------

    # return True if the type if is void*, False otherwise
    # @belongs: init

    def _is_void_ptr(self, t):
        if t is None:
            logging.error(f"Type {t} not found")
            return False
        t = self.dbops._get_typedef_dst(t)

        if t["class"] != "pointer":
            return False

        # we know it's a pointer
        dst_tid = t["refs"][0]
        dst_t = self.dbops.typemap[dst_tid]
        if dst_t is None:
            logging.error(f"Type {dst_tid} not found")
            return False

        if dst_t["class"] != "builtin":
            return False

        if dst_t["str"] == "void":
            return True

        return False

    # -------------------------------------------------------------------------

    # return True if a struct member is in use, False otherwise
    # @belongs: init
    def _is_member_in_use(self, type, type_name, member_idx):
        if type["class"] != "record":
            return True

        is_in_use = True
        field_name = type["refnames"][member_idx]

        # let's check if the field is used
        if type['id'] not in self.used_types_data:
            is_in_use = False
        elif "usedrefs" in type:
            # TODO: remove size check
            if member_idx < len(type["usedrefs"]) and -1 == type["usedrefs"][member_idx]:
                if self.args.debug_vars_init:
                    logging.info(
                        f"Detected that field {field_name} in {type_name} is not used")
                is_in_use = False
            if member_idx >= len(type["usedrefs"]):
                logging.warning(
                    f"Unable to check if {field_name} is used or not")

        return is_in_use

    # -------------------------------------------------------------------------

    # @belongs: init
    def _get_callref_from_deref(self, deref):
        if deref["kind"] == "offsetof":
            return False
        if "offsetrefs" in deref:
            for oref in deref["offsetrefs"]:
                if oref["kind"] == "callref":
                    return True

        return False

    # -------------------------------------------------------------------------

    # If there is a cast in the deref, return the associated data,
    # return None if no cast has been found
    # @belongs: init
    def _get_cast_from_deref(self, deref, f):
        if deref["kind"] == "offsetof":
            return None
        cast_tid = -1
        ret_val = None

        # TODO: implement "kind": "return" -> in that case we don't need to have
        # cast in the offsetrefs
        logging.debug(f"get cast from deref: {deref}")

        # first, check if we are not doing pointer arithmetic
        if deref["kind"] == "assign" and deref["offset"] != 21:
            self.debug_derefs(
                f"skipping deref associated with arithmetic {deref}")

        elif "offsetrefs" in deref:
            for oref in deref["offsetrefs"]:
                src_tid = -1
                src_root_tid = -1
                src_member = -1
                dst_deref = None
                if "cast" in oref:

                    # get the type we are casting to
                    cast_tid = oref["cast"]
                    cast_type = self.dbops.typemap[cast_tid]
                    id = oref["id"]

                    # get the type we are casting from
                    if oref["kind"] == "unary":
                        self.debug_derefs(
                            f"Unsupported deref type {oref['kind']}")
                        continue

                    elif oref["kind"] == "array":
                        array_deref = f["derefs"][oref['id']]
                        array_found = False
                        if array_deref["kind"] == "array":
                            for _oref in array_deref["offsetrefs"]:
                                if _oref["kind"] == "member":
                                    dst_deref = f["derefs"][_oref["id"]]
                                    array_found = True
                        if not array_found:
                            self.debug_derefs(
                                f"Unsupported deref type {oref['kind']}")
                            continue

                    elif oref["kind"] == "member":
                        if id >= len(f["derefs"]):
                            logging.error(
                                f"id {id} larger than the derefs size")
                            # sys.exit(1) <- uncomment for testing
                            continue
                        dst_deref = f["derefs"][id]
                        logging.debug(f"dst deref is {dst_deref}")

                    elif oref["kind"] == "assign":
                        self.debug_derefs(
                            f"Unsupported deref type {oref['kind']}")
                        continue

                    elif oref["kind"] == "function":
                        self.debug_derefs(
                            f"Unsupported deref type {oref['kind']}")
                        continue

                    elif oref["kind"] == "global":
                        self.debug_derefs(
                            f"Unsupported deref type {oref['kind']}")
                        continue

                    elif oref["kind"] == "local":
                        src_tid = f["locals"][oref["id"]]["type"]
                        # logging.error(
                        #    f"Unsupported deref type {oref['kind']}")
                        # continue

                    elif oref["kind"] == "parm":
                        dst_deref = f["locals"][id]

                    elif oref["kind"] == "callref":
                        # this happens when a return value of a function is casted to other type
                        dst_deref = None
                        # the source type in this case is the return type of the function
                        call_id = f["calls"][oref["id"]]
                        call = self.dbops.fnidmap[call_id]
                        if call is None:
                            self.debug_derefs(
                                f"Call not found in functions")
                            continue
                        src_tid = call["types"][0]

                        if deref["kind"] == "return":
                            cast_tid = f["types"][0]  # return type goes first
                            cast_type = self.dbops.typemap[cast_tid]
                            src_tid = oref["cast"]
                        elif deref["kind"] == "init":
                            # let's assume that the first oref is the
                            inited = deref["offsetrefs"][0]
                            # value that is being initialized
                            if inited["kind"] == "local":
                                cast_tid = f["locals"][inited["id"]]["type"]
                                cast_type = self.dbops.typemap[cast_tid]
                    else:
                        self.debug_derefs(
                            f"Unsupported deref type {oref['kind']}")
                        continue

                    if dst_deref is not None and "type" not in dst_deref:
                        self.debug_derefs(
                            f"Type not found in deref {dst_deref}")
                        # sys.exit(1) <- uncomment for testing
                        continue
                    src_root_tid = src_tid
                    if dst_deref is not None:
                        if isinstance(dst_deref["type"], list):
                            # kind == member
                            # Note: in the easy case we just derefernce a single member,
                            # but this could as well be something like a = b->c->d, so we need to
                            # get to the final member in the dereference "chain"

                            src_tid = dst_deref["type"][-1]
                            src_member = dst_deref["member"][-1]
                            src_root_tid = src_tid
                            src_tid = self.dbops._get_real_type(src_tid)
                        else:
                            # kind == parm
                            src_root_tid = dst_deref["type"]
                            src_tid = self.dbops._get_real_type(
                                dst_deref["type"])

                    src_type = self.dbops.typemap[src_tid]
                    src_root_type = src_type
                    # member is only meaningful for records
                    if src_type["class"] == "record":
                        # logging.info(f"src_tid = {src_tid} src_member = {src_member} dst_deref = {dst_deref} deref = {deref}")
                        if src_member != -1:
                            src_member_tid = src_type["refs"][src_member]
                            src_type = self.dbops.typemap[src_member_tid]
                        else:
                            src_member = Init.CAST_PTR_NO_MEMBER
                    else:
                        src_member = Init.CAST_PTR_NO_MEMBER

                    # let's check if the source and destination type don't have the same root:
                    dst_root = self.dbops._get_real_type(cast_tid)
                    if src_member == Init.CAST_PTR_NO_MEMBER:
                        if src_tid in self.deps.dup_types:
                            found = False
                            for t_id in self.deps.dup_types[src_tid]:
                                if t_id == dst_root:
                                    found = True
                                    break
                            if found:
                                continue
                        elif src_tid == dst_root:
                            continue
                    else:
                        src_root = self.dbops._get_real_type(src_member_tid)
                        if src_root in self.deps.dup_types:
                            found = False
                            for t_id in self.deps.dup_types[src_root]:
                                if t_id == dst_root:
                                    found = True
                                    break
                            if found:
                                continue
                        elif src_root == dst_root:
                            continue

                    if src_tid != cast_tid:
                        # last checks: see if we are not dealing with typedefs pointing to the same type:
                        if src_member == Init.CAST_PTR_NO_MEMBER:
                            src_no_typedef = self.dbops._get_typedef_dst(
                                self.dbops.typemap[src_root_tid])["id"]
                        else:
                            src_no_typedef = self.dbops._get_typedef_dst(
                                self.dbops.typemap[src_member_tid])["id"]
                        dst_no_typedef = self.dbops._get_typedef_dst(
                            self.dbops.typemap[cast_tid])["id"]
                        if src_no_typedef == dst_no_typedef:
                            self.debug_derefs(
                                f"source {src_tid} same as dst type {cast_tid}")
                            # sys.exit(1)
                            continue
                        # see if the size of source and dst type matches
                        # caveat: there could be a cast like this : int* ptr = (int*)&s->member
                        # member coult be u16 but its address used to process data as int - we currently
                        # don't support that scheme -> TBD
                        # src_size = self.dbops.typemap[src_no_typedef]["size"]
                        if src_member == Init.CAST_PTR_NO_MEMBER:
                            src_size = self.dbops.typemap[self.dbops._get_typedef_dst(
                                self.dbops.typemap[src_root_tid])["id"]]["size"]
                        else:
                            src_size = self.dbops.typemap[self.dbops._get_typedef_dst(
                                self.dbops.typemap[src_member_tid])["id"]]["size"]

                        dst_size = self.dbops.typemap[dst_no_typedef]["size"]
                        if src_size != dst_size:
                            self.debug_derefs(
                                f"Source {src_root_tid}:{src_size} and dst {dst_no_typedef}:{dst_size} type size mismatch - skipping cast")
                            # sys.exit(1)
                            continue

                        if not self._is_void_ptr(cast_type) or deref["kind"] == "return":
                            # in addition to void* casted to other types, we are also interested to know
                            # if non-void pointer types are casted

                            store_tid = -1
                            if src_root_type["class"] == "record" or src_root_type["class"] == "record_forward":
                                store_tid = src_tid
                            else:
                                store_tid = src_root_tid

                            if ret_val is None:
                                ret_val = {}
                            if store_tid not in ret_val:
                                ret_val[store_tid] = {}
                            if src_member not in ret_val[store_tid]:
                                ret_val[store_tid][src_member] = []
                            if cast_tid not in ret_val[store_tid][src_member]:
                                ret_val[store_tid][src_member].append(cast_tid)

        # take care of the duplicates
        if ret_val is not None:
            for src_tid in list(ret_val.keys()):
                if src_tid in self.deps.dup_types:
                    dups = self.deps.dup_types[src_tid]
                    for dup in dups:
                        if dup not in ret_val:
                            ret_val[dup] = copy.deepcopy(ret_val[src_tid])

        return ret_val

    # -------------------------------------------------------------------------

    # If there is an offsetof expression in the deref, return the associated data,
    # return None if no offsetof has been found
    # @belongs: init
    def _get_offsetof_from_deref(self, deref):

        if deref["kind"] != "offsetof":
            return None

        # it's a heuristic, but let's assume that when we use offsetof we actually mean to get from one type to another
        # in other words, let's treat it as a form of type cast

        dst_tid = deref["type"][0]

        # we are only interested in the last member, last type
        member_no = deref["member"][-1]
        src_tid = self.dbops.typemap[deref["type"][-1]]["refs"][member_no]

        ret_val = {}
        ret_val[src_tid] = [(deref["type"], deref["member"])]

        # take care of the duplicates:
        if src_tid in self.deps.dup_types:
            dups = self.deps.dup_types[src_tid]

            for dup in dups:
                if dup not in ret_val:
                    ret_val[dup] = copy.deepcopy(ret_val[src_tid])

        return ret_val

    # -------------------------------------------------------------------------

    # if there is a member access in the deref, return the associated data,
    # return None if no member access has been found
    # @belongs: init
    def _get_member_access_from_deref(self, deref):
        if deref["kind"] != "member":
            return None, None

        # filter out accesses by address as they distort derefs trace parsing
        for oref in deref["offsetrefs"]:
            if oref["kind"] == "address":
                self.debug_derefs("Ignoring member access on address")
                return None, None

        ret_val = {}
        access_order = []
        for mi in range(len(deref["access"])):
            t_id = deref["type"][mi]
            t = self.dbops.typemap[t_id]
            if deref["access"][mi] == 1:
                t_id = self.dbops._get_typedef_dst(t)['id']
                t_id = self.dbops._get_real_type(t_id)
                t = self.dbops.typemap[t_id]
            t = self.dbops._get_typedef_dst(t)
            t_id = t["id"]
            item = None
            if t_id not in ret_val:
                # we create a deep copy in order to avoid
                ret_val[t_id] = copy.deepcopy(t)
                # interfering with the db cache
                item = ret_val[t_id]
                # we will update the "usedrefs information"
                for i in range(len(item["usedrefs"])):
                    item["usedrefs"][i] = -1
                # logging.debug(f"processing deref {d}, t_id={t_id}, item={item}")
            else:
                item = ret_val[t_id]

            access_order.append(t_id)

            # let's make a note that the member is used
            member_id = deref["member"][mi]
            t_id = t["refs"][member_id]

            if item["usedrefs"][member_id] != -1 and item["usedrefs"][member_id] != t_id:
                logging.error(
                    f"This member had a different id: t_id={t_id}, member_id={member_id}, prev={item['usedrefs'][member_id]}, curr={t_id}")
                raise Exception("Breaking execution due to error")

            item["usedrefs"][member_id] = t_id

            # if the used member is a record itself, let's add it to the map in order
            # to mark that the type is used (this can help if we have a record type without any member usages)
            t_id = self.dbops._get_real_type(t_id)
            t = self.dbops.typemap[t_id]
            t = self.dbops._get_typedef_dst(t)
            t_id = t["id"]

            if t["class"] == "record" and t_id not in ret_val:
                # we create a deep copy in order to avoid
                ret_val[t_id] = copy.deepcopy(t)
                # interfering with the db cache
                item = ret_val[t_id]
                # we will update the "usedrefs information"
                for i in range(len(item["usedrefs"])):
                    item["usedrefs"][i] = -1

        # merge data from type dups
        for t_id in list(ret_val.keys()):
            if t_id in self.deps.dup_types:
                t = ret_val[t_id]
                dups = self.deps.dup_types[t_id]

                for dup in dups:
                    if dup in ret_val:
                        t2 = ret_val[dup]
                        for i in range(len(t["usedrefs"])):
                            if (t["usedrefs"][i] != -1 and t2["usedrefs"][i] == 1) or (t["usedrefs"][i] == -1 and t2["usedrefs"][i] != 1):
                                if t["usedrefs"][i] == -1:
                                    t["usedrefs"][i] = t2["usedrefs"][i]
                                else:
                                    t2["usedrefs"][i] = t["usedrefs"][i]

        # take type dups into account
        for t_id in list(ret_val.keys()):
            if t_id in self.deps.dup_types:
                dups = self.deps.dup_types[t_id]
                for dup in dups:
                    if dup not in ret_val:
                        ret_val[dup] = copy.deepcopy(ret_val[t_id])

        return ret_val, access_order

    # -------------------------------------------------------------------------

    # the idea behind this helper function is to discover all type casts across pointers
    # by using the dereference information stored in the functions metadata
    # This information can be used, e.g., to find the "real" type behind a void* pointer.
    # It can also be used to detect scenarios in which one type is used as a different type
    # after a cast (which in turn helps to find which member of that other types are in use in
    # case of structural types).
    # @belongs: init
    def _discover_casts(self, functions):

        for f_id in functions:

            f = self.dbops.fnidmap[f_id]
            if f is None:
                logging.info(f"Function id {f_id} not found among functions")
                continue
            cast_tid = -1

            for deref in f["derefs"]:

                if deref["kind"] != "offsetof":
                    cast_data = self._get_cast_from_deref(deref, f)

                    if cast_data is None:
                        continue
                    elif deref['expr'].lstrip().startswith('&'):
                        # workaround for a special case:
                        # we have found a cast but the expression in which it was detected
                        # is an address dereference
                        continue

                    for src_tid in cast_data:
                        if src_tid not in self.casted_pointers:
                            self.casted_pointers[src_tid] = cast_data[src_tid]
                        else:
                            for src_member in cast_data[src_tid]:
                                if src_member not in self.casted_pointers[src_tid]:
                                    self.casted_pointers[src_tid][src_member] = cast_data[src_tid][src_member]
                                else:
                                    for cast_tid in cast_data[src_tid][src_member]:
                                        if cast_tid not in self.casted_pointers[src_tid][src_member]:
                                            self.casted_pointers[src_tid][src_member].append(
                                                cast_tid)
                else:

                    # we are dealing with the offsetof construct

                    offsetof_data = self._get_offsetof_from_deref(deref)

                    if offsetof_data is None:
                        continue

                    for src_tid in offsetof_data:
                        if src_tid not in self.offset_pointers:
                            self.offset_pointers[src_tid] = offsetof_data[src_tid]
                        else:
                            for types, members in offsetof_data[src_tid]:
                                found = False
                                for t, m in self.offset_pointers[src_tid]:
                                    if t == types and m == members:
                                        found = True
                                        break
                                if found == False:
                                    self.offset_pointers[src_tid].append(
                                        (types, members))
                    # offsetpointers is a map that links internal types to their containing structures

        logging.info(
            f"We discovered the following void pointers cast data {self.casted_pointers}")

    # -------------------------------------------------------------------------

    # @belongs: init
    def _get_used_types_data(self):
        self.used_types_data = {}
        # at this point we know all the functions that are going to be a part of the off-target
        # based on that information let's find out which members of the structural types (records and unions) are used
        # we are going to leverage that information for a smarter, more focused data initialization

        logging.info("Capturing used types information")
        for f_id in self.cutoff.internal_funcs:
            f = self.dbops.fnidmap[f_id]
            if f is None:
                continue  # that's a funcdecl or unresolved func (unlikely)

            # we will extract the member usage from the "derefs" data
            if "derefs" not in f:
                continue

            for d in f["derefs"]:

                member_data, access_order = self._get_member_access_from_deref(
                    d)
                if member_data is None:
                    continue

                for t_id in member_data:
                    if t_id not in self.used_types_data:
                        self.used_types_data[t_id] = member_data[t_id]
                    else:
                        for i in range(len(member_data[t_id]["usedrefs"])):
                            used = member_data[t_id]["usedrefs"][i]
                            if "usedrefs" not in self.used_types_data[t_id]:
                                logging.error(
                                    f"usedrefs not found in type {t_id}")
                            if used != -1:
                                self.used_types_data[t_id]["usedrefs"][i] = used

        logging.info(
            f"Used types data captured, size is {len(self.used_types_data)}")

    # -------------------------------------------------------------------------

    # @belongs: init
    def _debug_print_typeuse_obj(self, obj, visited=None):
        members = []
        if visited is None:
            visited = set()
        if obj in visited:
            return
        visited.add(obj)
        logging.info(f"Obj: {obj}")

        for _type_id in obj.used_members:
            for member_id in obj.used_members[_type_id]:
                self._debug_print_typeuse_obj(
                    obj.used_members[_type_id][member_id], visited)
        for _type_id, member, _obj in obj.offsetof_types:
            self._debug_print_typeuse_obj(_obj, visited)

    # -------------------------------------------------------------------------

    # @belongs: codegen or init (used in init but more utility/generic kind)
    def _get_const_array_size(self, type):
        if type["class"] == "incomplete_array" and type["size"] == 0:
            return 0

        elem_type = type["refs"][0]
        elem_size = self.dbops.typemap[elem_type]["size"]
        if elem_size != 0:
            return type["size"] // elem_size
        else:
            return 0

    # -------------------------------------------------------------------------

    # @belongs: init/codegen -> in the end it would be the best to have the metadata generated by init and the code generation done by codegen
    def _generate_var_deinit(self, var):
        return f"aot_memory_free_ptr(&{var});\n"
