function UPDATE_qaqc_noqaqc_boolean_DB_NRS(channelInfo,level)
global dataWIP;
global DATE_PROGRAM_LAUNCHED

channelId=sort(str2double(channelInfo.channelId));

Filename_DB=fullfile(dataWIP,strcat('DB_Update_NRS_TABLE',DATE_PROGRAM_LAUNCHED,'.sql')); %%SQL COMMANDS to paste on PGadmin
fid_DB = fopen(Filename_DB, 'a+');

fprintf(fid_DB,'BEGIN;\n');
Number_channels_available=size(channelId,1);
if level == 0
    for j=1:Number_channels_available
        fprintf(fid_DB,'UPDATE anmn.nrs_parameters set no_qaqc_boolean=1 where channelid=%d;\n',channelId(j));
    end
    
elseif level== 1
    for j=1:Number_channels_available
        fprintf(fid_DB,'UPDATE anmn.nrs_parameters set qaqc_boolean=1 where channelid=%d;\n',channelId(j));
    end
end

fprintf(fid_DB,'COMMIT;\n');
fclose(fid_DB);

end